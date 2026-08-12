"""Training package with a local-only MLflow telemetry boundary."""

from __future__ import annotations

import os

# MLflow 3.15 enables client telemetry unless the host opts out. ModelGuard's training contract is
# local-first and must not create hidden network activity. Set the default before any training
# submodule can import MLflow; an operator can still make a deliberate process-level override.
os.environ.setdefault("MLFLOW_DISABLE_TELEMETRY", "true")
