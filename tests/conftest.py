"""Shared deterministic Phase 02 test fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest
from sklearn.calibration import CalibratedClassifierCV

from modelguard.core.config import AppEnvironment, Settings
from modelguard.core.serialization import write_json
from modelguard.training.config import TrainingConfig, load_training_config
from modelguard.training.pipeline import predict_positive_scores
from modelguard.training.workflow import (
    TrainingResult,
    generate_data_artifacts,
    train_from_artifacts,
)


@pytest.fixture
def valid_prediction_payload() -> dict[str, object]:
    """Canonical Phase 02 smoke row used by API tests."""

    return {
        "amount": 4200.0,
        "transaction_hour": 2,
        "velocity_1h": 8,
        "distance_from_home_km": 180.0,
        "device_risk_score": 0.82,
        "merchant_risk_score": 0.64,
        "is_new_device": True,
        "country_code": "EG",
        "device_type": "mobile",
    }


@pytest.fixture
def api_settings(audited_workspace: AuditedWorkspace) -> Settings:
    """Test-mode settings pointing at the session-scoped verified bundle."""

    return Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        model_bundle_path=audited_workspace.result.bundle_path,
        active_model_version=audited_workspace.config.model_version,
    )


@pytest.fixture(scope="session")
def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def training_config(repository_root: Path) -> TrainingConfig:
    return load_training_config(repository_root / "configs" / "phase-02-training.json")


def small_training_config(config: TrainingConfig, *, row_count: int = 700) -> TrainingConfig:
    return config.model_copy(
        update={"dataset": config.dataset.model_copy(update={"row_count": row_count})}
    )


@dataclass(frozen=True)
class AuditedWorkspace:
    root: Path
    config_path: Path
    config: TrainingConfig
    result: TrainingResult
    stage_events: tuple[str, ...]
    score_calls: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]


@pytest.fixture(scope="session")
def audited_workspace(
    tmp_path_factory: pytest.TempPathFactory,
    repository_root: Path,
) -> AuditedWorkspace:
    root = tmp_path_factory.mktemp("audited-phase02")
    config = small_training_config(
        load_training_config(repository_root / "configs" / "phase-02-training.json")
    )
    config_path = root / "training-config.json"
    write_json(config_path, config)
    output_root = root / "artifacts"
    generate_data_artifacts(config_path, output_root)
    stages: list[str] = []
    score_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def score_spy(estimator: CalibratedClassifierCV, features: pd.DataFrame) -> object:
        score_calls.append((tuple(features.index.astype(str)), tuple(stages)))
        return predict_positive_scores(estimator, features)

    result = train_from_artifacts(
        config_path,
        output_root,
        repository_root,
        score_predictor=score_spy,  # type: ignore[arg-type]
        stage_callback=stages.append,
    )
    return AuditedWorkspace(
        root=root,
        config_path=config_path,
        config=config,
        result=result,
        stage_events=tuple(stages),
        score_calls=tuple(score_calls),
    )
