"""API startup integration for exact AWS bundle hydration and fail-closed readiness."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

from modelguard.api.main import create_app
from modelguard.core.config import ApiAccessMode, AppEnvironment, EventSink, Settings
from modelguard.core.telemetry import PrometheusTelemetry
from modelguard.inference.loader import AwsHydratingModelLoader
from modelguard.monitoring.events import EventIdentity
from modelguard.storage.versioned_bundle import ActiveMonitoringPointer, VersionedBundleLocation
from modelguard.training.bundle import EXPECTED_FILENAMES, ValidatedBundleMetadata


class QuietLogger:
    def info(self, event: str, **fields: object) -> None:
        del event, fields

    def warning(self, event: str, **fields: object) -> None:
        del event, fields

    def error(self, event: str, **fields: object) -> None:
        del event, fields


class PointerSsm:
    def __init__(self, pointer: ActiveMonitoringPointer) -> None:
        self.pointer = pointer

    def get_parameter(self, **kwargs: Any) -> Mapping[str, Any]:
        assert kwargs == {
            "Name": "/modelguard-ai/demo/models/active",
            "WithDecryption": False,
        }
        return {
            "Parameter": {
                "Name": "/modelguard-ai/demo/models/active",
                "Type": "String",
                "Value": self.pointer.model_dump_json(),
                "Version": 1,
            }
        }


class ExactBundleS3:
    def __init__(self, bundle: Path, *, corrupt_manifest: bool = False) -> None:
        self.bundle = bundle
        self.corrupt_manifest = corrupt_manifest

    def get_bucket_location(self, **kwargs: Any) -> Mapping[str, Any]:
        assert kwargs == {"Bucket": "modelguard-test-models"}
        return {"LocationConstraint": None}

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]:
        filename = str(kwargs["Key"]).rsplit("/", 1)[-1]
        payload = (self.bundle / filename).read_bytes()
        if self.corrupt_manifest and filename == "manifest.json":
            payload = b"{}\n"
        return {
            "Body": BytesIO(payload),
            "ContentLength": len(payload),
            "VersionId": kwargs["VersionId"],
        }


def _pointer(target: EventIdentity) -> ActiveMonitoringPointer:
    return ActiveMonitoringPointer(
        target_identity=target,
        bundle=VersionedBundleLocation(
            bucket="modelguard-test-models",
            key_prefix="model-bundles/1.0.0/",
            object_version_ids={name: f"version-{name}" for name in EXPECTED_FILENAMES},
        ),
    )


def _settings(destination: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env=AppEnvironment.AWS,
        event_sink=EventSink.DISABLED,
        api_access_mode=ApiAccessMode.HTTP_CIDR_ONLY,
        alb_allowed_cidr="203.0.113.8/32",
        model_bundle_path=destination,
        active_model_version="1.0.0",
        model_bucket="modelguard-test-models",
        active_model_ssm_parameter="/modelguard-ai/demo/models/active",
    )


def test_api_serves_only_after_exact_aws_bundle_is_atomically_verified(
    tmp_path: Path,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
    valid_prediction_payload: dict[str, object],
) -> None:
    destination = tmp_path / "runtime" / "model-bundle"
    settings = _settings(destination)
    app = create_app(
        settings,
        model_loader=AwsHydratingModelLoader(
            ssm_client=PointerSsm(_pointer(monitoring_target)),
            s3_client=ExactBundleS3(monitoring_metadata.path),
        ),
        telemetry=PrometheusTelemetry(),
        logger=QuietLogger(),
    )

    async def exercise() -> None:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                assert (await client.get("/health/ready")).json() == {"status": "ready"}
                version = (await client.get("/version")).json()
                prediction = await client.post(
                    "/v1/predict",
                    json=valid_prediction_payload,
                    headers={"x-forwarded-proto": "http"},
                )
                assert version["model_version"] == "1.0.0"
                assert version["manifest_sha256"] == monitoring_target.bundle_manifest_sha256
                assert prediction.status_code == 200

    asyncio.run(exercise())
    assert destination.is_dir()


def test_api_corrupt_aws_bundle_never_becomes_ready_or_publishes_partial_bytes(
    tmp_path: Path,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
    valid_prediction_payload: dict[str, object],
) -> None:
    destination = tmp_path / "runtime" / "model-bundle"
    settings = _settings(destination)
    app = create_app(
        settings,
        model_loader=AwsHydratingModelLoader(
            ssm_client=PointerSsm(_pointer(monitoring_target)),
            s3_client=ExactBundleS3(monitoring_metadata.path, corrupt_manifest=True),
        ),
        telemetry=PrometheusTelemetry(),
        logger=QuietLogger(),
    )

    async def exercise() -> None:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                ready = await client.get("/health/ready")
                prediction = await client.post(
                    "/v1/predict",
                    json=valid_prediction_payload,
                    headers={"x-forwarded-proto": "http"},
                )
                assert ready.status_code == 503
                assert prediction.status_code == 503
                assert prediction.json()["code"] == "model_not_ready"

    asyncio.run(exercise())
    assert not destination.exists()
    assert not list(destination.parent.glob(".model-bundle.hydrate-*"))
