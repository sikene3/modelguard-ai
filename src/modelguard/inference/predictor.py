"""Single-load model predictor and locked threshold decision policy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

from modelguard.training.bundle import VerifiedBundle


class RiskDecision(StrEnum):
    """The two locked API decisions."""

    LOW_RISK = "low_risk"
    HIGH_RISK = "high_risk"


class PredictionError(RuntimeError):
    """Raised when a loaded model violates the runtime prediction contract."""


@dataclass(frozen=True)
class Prediction:
    """One finite score and threshold-derived decision."""

    risk_score: float
    decision: RiskDecision
    model_version: str


class Predictor:
    """Own one verified in-memory model for the lifetime of an API process."""

    def __init__(self, bundle: VerifiedBundle) -> None:
        self._bundle = bundle
        classes = np.asarray(bundle.model.classes_)
        positive_positions = np.flatnonzero(classes == 1)
        if len(positive_positions) != 1:
            raise PredictionError("loaded model must expose exactly one positive class")
        self._positive_index = int(positive_positions[0])

    @property
    def model_version(self) -> str:
        return self._bundle.metadata.identity.model_version

    @property
    def manifest_sha256(self) -> str:
        return self._bundle.metadata.identity.manifest_sha256

    @property
    def input_schema_version(self) -> str:
        return self._bundle.metadata.input_schema.schema_version

    def predict(self, features: Mapping[str, object]) -> Prediction:
        """Score one already-validated request in the bundle's canonical feature order."""

        feature_order = self._bundle.metadata.input_schema.feature_order
        if set(features) != set(feature_order):
            raise PredictionError("prediction feature set differs from the verified schema")
        frame = pd.DataFrame([features], columns=feature_order)
        try:
            probabilities = np.asarray(self._bundle.model.predict_proba(frame), dtype=float)
            if probabilities.shape[0] != 1 or self._positive_index >= probabilities.shape[1]:
                raise ValueError("unexpected prediction shape")
            score = float(probabilities[0, self._positive_index])
        except (AttributeError, IndexError, TypeError, ValueError) as error:
            raise PredictionError("model prediction failed its output contract") from error
        if not np.isfinite(score) or not 0.0 <= score <= 1.0:
            raise PredictionError("model score must be finite and in [0, 1]")
        threshold = self._bundle.metadata.threshold.threshold
        decision = RiskDecision.HIGH_RISK if score >= threshold else RiskDecision.LOW_RISK
        return Prediction(
            risk_score=score,
            decision=decision,
            model_version=self.model_version,
        )
