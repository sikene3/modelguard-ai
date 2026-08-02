"""Inference-specific wrapper around ordered Phase 02 bundle verification."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from modelguard.core.config import Settings
from modelguard.training.bundle import BundleVerificationError, VerifiedBundle, verify_bundle


class ModelLoadFailure(StrEnum):
    """Sanitized readiness reasons that never contain filesystem details."""

    INVALID_BUNDLE = "invalid_bundle"
    MISSING_BUNDLE = "missing_bundle"
    UNEXPECTED_FAILURE = "unexpected_failure"
    VERSION_MISMATCH = "version_mismatch"


class ModelLoadError(RuntimeError):
    """A model-load failure safe to classify in logs and telemetry."""

    def __init__(self, reason: ModelLoadFailure) -> None:
        super().__init__(reason.value)
        self.reason = reason


class ModelLoader(Protocol):
    """Dependency-injected startup model loader."""

    def load(self, settings: Settings) -> VerifiedBundle:
        """Return one fully verified and smoke-tested model bundle."""


class VerifiedModelLoader:
    """Load a trusted configured bundle once after every ordered integrity check."""

    def load(self, settings: Settings) -> VerifiedBundle:
        if not settings.model_bundle_path.exists():
            raise ModelLoadError(ModelLoadFailure.MISSING_BUNDLE)
        try:
            verified = verify_bundle(
                settings.model_bundle_path,
                trusted_origin=settings.model_bundle_trusted_origin,
            )
        except BundleVerificationError as error:
            raise ModelLoadError(ModelLoadFailure.INVALID_BUNDLE) from error
        except (OSError, EOFError, ImportError, TypeError, ValueError) as error:
            raise ModelLoadError(ModelLoadFailure.UNEXPECTED_FAILURE) from error
        if verified.metadata.identity.model_version != settings.active_model_version:
            raise ModelLoadError(ModelLoadFailure.VERSION_MISMATCH)
        return verified
