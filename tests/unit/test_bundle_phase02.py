"""Immutable bundle, corruption ordering, and reload parity tests."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, NoReturn, cast

import numpy as np
import pytest
from sklearn.calibration import CalibratedClassifierCV

from modelguard.core.hashing import raw_file_hash, sha256_file
from modelguard.training.bundle import (
    CHECKSUM_FILENAME,
    EXPECTED_FILENAMES,
    MANIFEST_FILENAME,
    PAYLOAD_FILENAMES,
    BundleVerificationError,
    build_immutable_bundle,
    inspect_bundle,
    verify_bundle,
)
from modelguard.training.workflow import (
    DataArtifactPaths,
    load_training_inputs,
    materialize_split_frames,
)


def _copy_bundle(source: Path, destination: Path) -> Path:
    return Path(shutil.copytree(source, destination))


def _rewrite_checksums(bundle: Path) -> None:
    lines = [f"{sha256_file(bundle / name)}  {name}" for name in sorted(PAYLOAD_FILENAMES)]
    (bundle / CHECKSUM_FILENAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _rewrite_manifest_payload_hash(bundle: Path, filename: str) -> None:
    manifest_path = bundle / MANIFEST_FILENAME
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["bundle_payload_hashes"][filename] = raw_file_hash(bundle / filename).model_dump(
        mode="json"
    )
    manifest_path.write_text(
        json.dumps(manifest_data, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _rewrite_checksums(bundle)


def test_bundle_has_exact_seven_files_and_durable_identity(audited_workspace: Any) -> None:
    bundle = audited_workspace.result.bundle_path
    metadata = inspect_bundle(bundle)

    assert {path.name for path in bundle.iterdir()} == EXPECTED_FILENAMES
    assert metadata.identity.model_version == audited_workspace.config.model_version
    assert metadata.identity.manifest_sha256 == sha256_file(bundle / MANIFEST_FILENAME)
    checksum_lines = (bundle / CHECKSUM_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(checksum_lines) == 6
    assert CHECKSUM_FILENAME not in {line.split("  ")[1] for line in checksum_lines}


@pytest.mark.parametrize("filename", sorted(EXPECTED_FILENAMES))
def test_each_bundle_file_corruption_is_rejected_before_deserialization(
    filename: str,
    audited_workspace: Any,
    tmp_path: Path,
) -> None:
    corrupted = _copy_bundle(
        audited_workspace.result.bundle_path, tmp_path / f"corrupt-{filename.replace('.', '-')}"
    )
    with (corrupted / filename).open("ab") as file_handle:
        file_handle.write(b"corruption")
    loader_called = False

    def forbidden_loader(_: Path) -> NoReturn:
        nonlocal loader_called
        loader_called = True
        raise AssertionError("joblib loader must not run")

    with pytest.raises(BundleVerificationError):
        verify_bundle(corrupted, trusted_origin=True, model_loader=forbidden_loader)
    assert loader_called is False


def test_recomputed_checksum_cannot_hide_cross_file_payload_mismatch(
    audited_workspace: Any,
    tmp_path: Path,
) -> None:
    changed = _copy_bundle(audited_workspace.result.bundle_path, tmp_path / "recomputed")
    threshold_path = changed / "threshold.json"
    threshold_data = json.loads(threshold_path.read_text(encoding="utf-8"))
    threshold_data["locked_at"] = "2030-01-01T00:00:00Z"
    threshold_path.write_text(
        json.dumps(threshold_data, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _rewrite_checksums(changed)

    with pytest.raises(BundleVerificationError, match="manifest payload hash mismatch"):
        inspect_bundle(changed)


def test_recomputed_manifest_hash_cannot_hide_threshold_evidence_mismatch(
    audited_workspace: Any,
    tmp_path: Path,
) -> None:
    changed = _copy_bundle(audited_workspace.result.bundle_path, tmp_path / "threshold-mismatch")
    threshold_path = changed / "threshold.json"
    threshold_data = json.loads(threshold_path.read_text(encoding="utf-8"))
    threshold_data["selected_false_positives"] += 1
    threshold_data["selected_synthetic_cost"] += 1
    threshold_path.write_text(
        json.dumps(threshold_data, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _rewrite_manifest_payload_hash(changed, "threshold.json")

    with pytest.raises(BundleVerificationError, match="locked threshold differs"):
        inspect_bundle(changed)


def test_manifest_seed_must_match_embedded_configuration(
    audited_workspace: Any,
    tmp_path: Path,
) -> None:
    changed = _copy_bundle(audited_workspace.result.bundle_path, tmp_path / "seed-mismatch")
    manifest_path = changed / MANIFEST_FILENAME
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["seeds"]["dataset_seed"] += 1
    manifest_path.write_text(
        json.dumps(manifest_data, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _rewrite_checksums(changed)

    with pytest.raises(BundleVerificationError, match="seeds do not match"):
        inspect_bundle(changed)


@pytest.mark.parametrize("mutation", ["missing", "extra", "symlink"])
def test_structure_rejects_missing_extra_and_symlink_before_checksums_or_joblib(
    mutation: str,
    audited_workspace: Any,
    tmp_path: Path,
) -> None:
    changed = _copy_bundle(audited_workspace.result.bundle_path, tmp_path / f"structure-{mutation}")
    if mutation == "missing":
        (changed / "metrics.json").unlink()
    elif mutation == "extra":
        (changed / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    else:
        model_path = changed / "model.joblib"
        model_path.unlink()
        os.symlink(audited_workspace.result.bundle_path / "model.joblib", model_path)
    loader_called = False

    def forbidden_loader(_: Path) -> NoReturn:
        nonlocal loader_called
        loader_called = True
        raise AssertionError("joblib loader must not run")

    with pytest.raises(BundleVerificationError):
        verify_bundle(changed, trusted_origin=True, model_loader=forbidden_loader)
    assert loader_called is False


def test_untrusted_origin_never_reaches_joblib_loader(audited_workspace: Any) -> None:
    loader_called = False

    def forbidden_loader(_: Path) -> NoReturn:
        nonlocal loader_called
        loader_called = True
        raise AssertionError("untrusted joblib must not load")

    with pytest.raises(BundleVerificationError, match="trusted origin"):
        verify_bundle(
            audited_workspace.result.bundle_path,
            trusted_origin=False,
            model_loader=forbidden_loader,
        )
    assert loader_called is False


def test_bundle_refuses_overwrite_and_cleans_partial_temporary_sibling(
    audited_workspace: Any,
    tmp_path: Path,
) -> None:
    verified = verify_bundle(audited_workspace.result.bundle_path, trusted_origin=True)
    metadata = verified.metadata
    estimator = cast(CalibratedClassifierCV, verified.model)

    with pytest.raises(FileExistsError, match="already exists"):
        build_immutable_bundle(
            audited_workspace.result.bundle_path.parent,
            model_version=metadata.manifest.model_version,
            estimator=estimator,
            input_schema=metadata.input_schema,
            metrics=metadata.metrics,
            threshold=metadata.threshold,
            baseline=metadata.baseline,
            manifest_factory=lambda _: metadata.manifest,
        )

    partial_parent = tmp_path / "partial-bundles"

    def failing_dumper(_: object, __: Path) -> NoReturn:
        raise RuntimeError("injected serialization failure")

    with pytest.raises(RuntimeError, match="injected"):
        build_immutable_bundle(
            partial_parent,
            model_version="2.0.0",
            estimator=estimator,
            input_schema=metadata.input_schema,
            metrics=metadata.metrics,
            threshold=metadata.threshold,
            baseline=metadata.baseline,
            manifest_factory=lambda _: metadata.manifest,
            model_dumper=failing_dumper,
        )
    assert partial_parent.is_dir()
    assert list(partial_parent.iterdir()) == []


def test_reloaded_model_prediction_parity_on_held_out_rows(audited_workspace: Any) -> None:
    verified = verify_bundle(audited_workspace.result.bundle_path, trusted_origin=True)
    inputs = load_training_inputs(
        audited_workspace.config,
        DataArtifactPaths(audited_workspace.root / "artifacts" / "data"),
    )
    frames = materialize_split_frames(inputs)
    reloaded_probabilities = np.asarray(
        verified.model.predict_proba(frames.test_features), dtype=float
    )
    positive_index = int(np.flatnonzero(np.asarray(verified.model.classes_) == 1)[0])

    np.testing.assert_allclose(
        reloaded_probabilities[:, positive_index],
        audited_workspace.result.test_scores,
        rtol=0.0,
        atol=1e-15,
    )
