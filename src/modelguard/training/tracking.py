"""Explicit local-file MLflow logging without autologging."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, cast

from mlflow import MlflowClient
from mlflow import environment_variables as mlflow_environment_variables

from modelguard.core.serialization import canonical_json_bytes
from modelguard.training.config import TrainingConfig
from modelguard.training.evaluate import EvaluationMetrics, MetricValue, ThresholdSelectionEvidence


class _BooleanEnvironmentVariable(Protocol):
    def is_set(self) -> bool: ...

    def get(self) -> bool: ...

    def set(self, value: bool) -> None: ...

    def unset(self) -> None: ...


def create_local_mlflow_client(tracking_uri: str) -> MlflowClient:
    """Construct a local file-store client across supported MLflow minor releases."""

    raw_file_store_opt_in = getattr(
        mlflow_environment_variables,
        "MLFLOW_ALLOW_FILE_STORE",
        None,
    )
    if raw_file_store_opt_in is None:
        return MlflowClient(tracking_uri=tracking_uri)

    file_store_opt_in = cast(_BooleanEnvironmentVariable, raw_file_store_opt_in)
    previously_set = file_store_opt_in.is_set()
    previous_value = file_store_opt_in.get()
    file_store_opt_in.set(True)
    try:
        client = MlflowClient(tracking_uri=tracking_uri)
    finally:
        if previously_set:
            file_store_opt_in.set(previous_value)
        else:
            file_store_opt_in.unset()
    return client


def _parameter_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list, tuple)):
        return canonical_json_bytes(value).decode("utf-8")
    return str(value)


def _flatten_parameters(value: Any, *, prefix: str = "") -> dict[str, str]:
    if isinstance(value, Mapping):
        flattened: dict[str, str] = {}
        for key in sorted(value):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            child = value[key]
            if isinstance(child, Mapping):
                flattened.update(_flatten_parameters(child, prefix=child_prefix))
            else:
                flattened[child_prefix] = _parameter_value(child)
        return flattened
    return {prefix: _parameter_value(value)}


class LocalMlflowRun:
    """Small explicit MLflow client wrapper tied to a local ``file:`` store."""

    def __init__(
        self,
        output_root: Path,
        config: TrainingConfig,
        *,
        tags: Mapping[str, str],
    ) -> None:
        # MLflow rejects a file-store root below a path segment literally named
        # ``artifacts`` because that name is reserved for run artifacts. Keep the
        # tracking store as a sibling of the generated artifact root.
        tracking_root = (output_root.parent / config.mlflow.tracking_subdirectory).resolve()
        tracking_root.mkdir(parents=True, exist_ok=True)
        self.tracking_uri = tracking_root.as_uri()
        if not self.tracking_uri.startswith("file:"):
            raise ValueError("Phase 02 MLflow tracking must use a local file: URI")
        self.client = create_local_mlflow_client(self.tracking_uri)
        experiment = self.client.get_experiment_by_name(config.mlflow.experiment_name)
        if experiment is None:
            experiment_id = self.client.create_experiment(config.mlflow.experiment_name)
        else:
            experiment_id = experiment.experiment_id
        # MLflow 3.9's file store can validate the just-created directory too early when
        # create_run receives tags. Create the run first, then write the explicit tags.
        run = self.client.create_run(experiment_id)
        self.run_id = run.info.run_id
        self._terminated = False
        for key, value in tags.items():
            self.client.set_tag(self.run_id, key, value)

    def log_configuration(self, config: TrainingConfig) -> None:
        """Log every explicit versioned parameter using stable flattened names."""

        parameters = _flatten_parameters(
            config.model_dump(mode="json", by_alias=True), prefix="config"
        )
        for key, value in parameters.items():
            self.client.log_param(self.run_id, key, value)

    def log_evaluation(
        self,
        test_metrics: EvaluationMetrics,
        validation_evidence: ThresholdSelectionEvidence,
    ) -> None:
        """Log held-out metrics and namespaced threshold evidence, never training metrics."""

        values: dict[str, float] = {
            "test.row_count": float(test_metrics.row_count),
            "test.threshold": test_metrics.threshold,
            "test.synthetic_cost": float(test_metrics.synthetic_cost),
            "validation_threshold.selected": validation_evidence.selected.threshold,
            "validation_threshold.synthetic_cost": float(
                validation_evidence.selected.synthetic_cost
            ),
            "validation_threshold.false_negatives": float(
                validation_evidence.selected.false_negatives
            ),
            "validation_threshold.false_positives": float(
                validation_evidence.selected.false_positives
            ),
        }
        named_metrics: dict[str, MetricValue] = {
            "test.average_precision": test_metrics.average_precision,
            "test.prevalence": test_metrics.prevalence,
            "test.ap_lift": test_metrics.ap_lift,
            "test.roc_auc": test_metrics.roc_auc,
            "test.brier_score": test_metrics.brier_score,
            "test.log_loss": test_metrics.log_loss,
            "test.accuracy": test_metrics.confusion_rates.accuracy,
            "test.precision": test_metrics.confusion_rates.precision,
            "test.recall": test_metrics.confusion_rates.recall,
            "test.f1": test_metrics.confusion_rates.f1,
            "test.synthetic_cost_per_event": test_metrics.synthetic_cost_per_event,
        }
        for key, metric in named_metrics.items():
            if metric.value is not None:
                values[key] = metric.value
        for key, value in values.items():
            self.client.log_metric(self.run_id, key, value)

    def set_tag(self, key: str, value: str) -> None:
        self.client.set_tag(self.run_id, key, value)

    def log_artifact(self, path: Path, *, artifact_path: str) -> None:
        self.client.log_artifact(self.run_id, str(path), artifact_path=artifact_path)

    def finish(self) -> None:
        if not self._terminated:
            self.client.set_terminated(self.run_id, status="FINISHED")
            self._terminated = True

    def fail(self) -> None:
        if not self._terminated:
            self.client.set_terminated(self.run_id, status="FAILED")
            self._terminated = True
