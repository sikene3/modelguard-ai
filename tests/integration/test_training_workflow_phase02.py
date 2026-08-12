"""Audited workflow, local MLflow, and CLI integration tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from modelguard.core.serialization import write_json
from modelguard.data.split import membership_hash
from modelguard.training.bundle import EXPECTED_FILENAMES
from modelguard.training.cli import main as cli_main
from modelguard.training.config import TrainingConfig
from modelguard.training.tracking import create_local_mlflow_client
from modelguard.training.workflow import (
    EVALUATION_SEQUENCE,
    DataArtifactPaths,
    load_training_inputs,
    materialize_split_frames,
)


def test_fresh_training_process_disables_mlflow_client_telemetry(
    repository_root: Path,
) -> None:
    environment = os.environ.copy()
    for name in (
        "MLFLOW_DISABLE_TELEMETRY",
        "DO_NOT_TRACK",
        "PYTEST_CURRENT_TEST",
        "GITHUB_ACTIONS",
        "CI",
        "CIRCLECI",
        "GITLAB_CI",
        "JENKINS_URL",
        "TRAVIS",
        "TF_BUILD",
        "BITBUCKET_BUILD_NUMBER",
        "CODEBUILD_BUILD_ARN",
        "BUILDKITE",
        "TEAMCITY_VERSION",
        "CLOUD_RUN_EXECUTION",
    ):
        environment.pop(name, None)
    probe = """
import json
import os
import tempfile
from pathlib import Path

from modelguard.training.tracking import create_local_mlflow_client
from mlflow.telemetry import get_telemetry_client

with tempfile.TemporaryDirectory() as directory:
    client = create_local_mlflow_client(Path(directory).resolve().as_uri())
    client.search_experiments()
print(json.dumps({
    "disabled": os.environ.get("MLFLOW_DISABLE_TELEMETRY"),
    "telemetry_client_is_none": get_telemetry_client() is None,
}))
"""

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "disabled": "true",
        "telemetry_client_is_none": True,
    }


def test_workflow_sequence_proves_test_scoring_occurs_only_after_threshold_lock(
    audited_workspace: Any,
) -> None:
    result = audited_workspace.result
    assert result.evaluation_sequence == EVALUATION_SEQUENCE
    assert audited_workspace.stage_events == EVALUATION_SEQUENCE
    assert len(audited_workspace.score_calls) == 3

    inputs = load_training_inputs(
        audited_workspace.config,
        DataArtifactPaths(audited_workspace.root / "artifacts" / "data"),
    )
    frames = materialize_split_frames(inputs)
    validation_ids, validation_stages = audited_workspace.score_calls[0]
    training_ids, training_stages = audited_workspace.score_calls[1]
    test_ids, test_stages = audited_workspace.score_calls[2]
    assert set(validation_ids) == set(frames.validation_features.index.astype(str))
    assert set(training_ids) == set(frames.training_features.index.astype(str))
    assert set(test_ids) == set(frames.test_features.index.astype(str))
    assert "validation_threshold_locked" not in validation_stages
    assert "validation_threshold_locked" in training_stages
    assert "validation_threshold_locked" in test_stages
    assert "held_out_test_scored_once" not in test_stages

    manifest = result.bundle_path / "manifest.json"
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    train_ids_list = frames.training_features.index.astype(str).tolist()
    assert manifest_data["calibration_audit"]["training_membership_hash"] == membership_hash(
        train_ids_list
    ).model_dump(mode="json")


def test_public_metrics_are_held_out_and_cost_reconciles(audited_workspace: Any) -> None:
    metrics = audited_workspace.result.metrics
    held_out = metrics.held_out_test
    counts = held_out.confusion_counts

    assert metrics.public_headline_scope == "held_out_test"
    assert held_out.evaluation_scope == "held_out_test_once_after_threshold_lock"
    assert not any(key.startswith("train") for key in held_out.model_dump())
    assert held_out.synthetic_cost == 10 * counts.false_negatives + counts.false_positives
    assert held_out.synthetic_cost_per_event.value == held_out.synthetic_cost / held_out.row_count
    assert held_out.ap_lift.value == held_out.average_precision.value / held_out.prevalence.value


def test_mlflow_run_has_explicit_content_and_no_autolog(audited_workspace: Any) -> None:
    result = audited_workspace.result
    client = create_local_mlflow_client(result.mlflow_tracking_uri)
    experiment = client.get_experiment_by_name(audited_workspace.config.mlflow.experiment_name)
    assert experiment is not None
    runs = client.search_runs([experiment.experiment_id])

    assert len(runs) == 1
    run = runs[0]
    assert run.info.run_id == result.mlflow_run_id
    assert run.info.status == "FINISHED"
    assert run.data.params["config.calibration.n_splits"] == "5"
    assert run.data.params["config.calibration.method"] == "sigmoid"
    assert run.data.params["config.calibration.ensemble"] == "true"
    assert run.data.params["config.logistic_regression.class_weight"] == "null"
    assert "test.average_precision" in run.data.metrics
    assert "test.synthetic_cost_per_event" in run.data.metrics
    assert "validation_threshold.selected" in run.data.metrics
    assert not any(name.startswith("train") for name in run.data.metrics)
    assert run.data.tags["mlflow.autolog"] == "false"
    assert run.data.tags["manifest_sha256"] == result.identity.manifest_sha256

    artifact_roots = {item.path for item in client.list_artifacts(run.info.run_id)}
    assert {"bundle", "cards", "data", "plots"}.issubset(artifact_roots)
    bundle_artifacts = {
        Path(item.path).name for item in client.list_artifacts(run.info.run_id, "bundle")
    }
    assert bundle_artifacts == EXPECTED_FILENAMES
    plot_artifacts = {
        Path(item.path).name for item in client.list_artifacts(run.info.run_id, "plots")
    }
    assert plot_artifacts == {"confusion_matrix_plot.html", "reliability_plot.html"}


def test_generate_train_inspect_verify_cli_end_to_end(
    tmp_path: Path,
    repository_root: Path,
    training_config: TrainingConfig,
    capsys: Any,
) -> None:
    config = training_config.model_copy(
        update={"dataset": training_config.dataset.model_copy(update={"row_count": 500})}
    )
    config_path = tmp_path / "cli-config.json"
    write_json(config_path, config)
    output_root = tmp_path / "cli-artifacts"
    bundle = output_root / "model-bundles" / config.model_version

    assert (
        cli_main(
            [
                "generate",
                "--config",
                str(config_path),
                "--output-root",
                str(output_root),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "generated"
    assert (
        cli_main(
            [
                "train",
                "--config",
                str(config_path),
                "--output-root",
                str(output_root),
                "--repository-root",
                str(repository_root),
            ]
        )
        == 0
    )
    trained_output = json.loads(capsys.readouterr().out)
    assert trained_output["status"] == "trained"
    assert trained_output["held_out_average_precision"] is not None

    assert cli_main(["inspect", "--bundle", str(bundle)]) == 0
    inspected_output = json.loads(capsys.readouterr().out)
    assert inspected_output["status"] == "valid_metadata"
    assert inspected_output["deserialized_model"] is False

    assert cli_main(["verify", "--bundle", str(bundle)]) == 1
    assert "trusted-origin" in capsys.readouterr().err
    assert cli_main(["verify", "--bundle", str(bundle), "--trusted-origin"]) == 0
    verified_output = json.loads(capsys.readouterr().out)
    assert verified_output["status"] == "verified"
    assert 0.0 <= verified_output["smoke_score"] <= 1.0

    tracking_uri = (output_root.parent / config.mlflow.tracking_subdirectory).resolve().as_uri()
    client = create_local_mlflow_client(tracking_uri)
    experiment = client.get_experiment_by_name(config.mlflow.experiment_name)
    assert experiment is not None
    assert len(client.search_runs([experiment.experiment_id])) == 1
