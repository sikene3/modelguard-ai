"""Phase 03 prediction-event seam; persistence is intentionally deferred to Phase 04."""

from __future__ import annotations

from typing import Protocol

from modelguard.inference.predictor import Prediction


class PredictionEventSink(Protocol):
    """Minimal async seam bounded by API timeouts and graceful shutdown."""

    async def emit(self, prediction: Prediction) -> None:
        """Accept a prediction notification without controlling request success."""

    async def close(self) -> None:
        """Flush/close any future sink resources during graceful shutdown."""


class NoOpPredictionEventSink:
    """Phase 03 default: deliberately performs no event logging or network I/O."""

    async def emit(self, prediction: Prediction) -> None:
        del prediction

    async def close(self) -> None:
        return None
