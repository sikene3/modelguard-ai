"""Inference-specific wrapper around ordered Phase 02 bundle verification."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, cast

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from modelguard.core.config import AppEnvironment, Settings
from modelguard.storage.versioned_bundle import (
    AtomicVersionedBundleInstaller,
    SsmPointerClient,
    SsmTargetSnapshotResolver,
    VersionedObjectClient,
    require_exact_bucket_region,
)
from modelguard.training.bundle import BundleVerificationError, VerifiedBundle, verify_bundle


class ModelLoadFailure(StrEnum):
    """Sanitized readiness reasons that never contain filesystem details."""

    INVALID_BUNDLE = "invalid_bundle"
    MISSING_BUNDLE = "missing_bundle"
    HYDRATION_FAILURE = "hydration_failure"
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


class AwsHydratingModelLoader:
    """Hydrate an exact SSM/S3 bundle with task-role credentials, then deserialize once."""

    def __init__(
        self,
        *,
        ssm_client: SsmPointerClient | None = None,
        s3_client: VersionedObjectClient | None = None,
    ) -> None:
        self._ssm_client = ssm_client
        self._s3_client = s3_client

    @staticmethod
    def _client_config() -> Config:
        return Config(
            connect_timeout=1.0,
            read_timeout=5.0,
            retries={"max_attempts": 3, "mode": "standard"},
            user_agent_extra="modelguard-runtime-hydration/1",
        )

    def _clients(self, region: str) -> tuple[SsmPointerClient, VersionedObjectClient]:
        config = self._client_config()
        ssm_client = self._ssm_client
        s3_client = self._s3_client
        if ssm_client is None:
            # No profile or credential value is supplied: ECS resolves the task role through the
            # default SDK credential provider chain.
            ssm_client = cast(
                SsmPointerClient,
                boto3.client("ssm", region_name=region, config=config),
            )
        if s3_client is None:
            s3_client = cast(
                VersionedObjectClient,
                boto3.client("s3", region_name=region, config=config),
            )
        return ssm_client, s3_client

    def load(self, settings: Settings) -> VerifiedBundle:
        if settings.app_env is not AppEnvironment.AWS:
            raise ModelLoadError(ModelLoadFailure.HYDRATION_FAILURE)
        if not settings.model_bucket or not settings.active_model_ssm_parameter:
            raise ModelLoadError(ModelLoadFailure.HYDRATION_FAILURE)
        try:
            ssm_client, s3_client = self._clients(settings.aws_region)
            require_exact_bucket_region(
                s3_client,
                bucket=settings.model_bucket,
                expected_region=settings.aws_region,
            )
            pointer = SsmTargetSnapshotResolver(
                ssm_client,
                parameter_name=settings.active_model_ssm_parameter,
            ).resolve_once()
            installed = AtomicVersionedBundleInstaller(s3_client).install(
                pointer,
                destination=settings.model_bundle_path,
                expected_bucket=settings.model_bucket,
                expected_model_version=settings.active_model_version,
            )
            verified_settings = settings.model_copy(
                update={
                    "model_bundle_path": installed.path,
                    "model_bundle_trusted_origin": True,
                }
            )
            return VerifiedModelLoader().load(verified_settings)
        except ModelLoadError:
            raise
        except (BotoCoreError, ClientError, OSError, TypeError, ValueError) as error:
            raise ModelLoadError(ModelLoadFailure.HYDRATION_FAILURE) from error


def default_model_loader(settings: Settings) -> ModelLoader:
    """Select AWS hydration only for the actual AWS runtime environment."""

    if settings.app_env is AppEnvironment.AWS:
        return AwsHydratingModelLoader()
    return VerifiedModelLoader()
