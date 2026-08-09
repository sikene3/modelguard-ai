"""Adversarial create-only publication and active/previous promotion tests."""

from __future__ import annotations

import io
import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from scripts import model_bundle_publisher
from scripts.model_bundle_publisher import _parser

from modelguard.core.hashing import sha256_bytes
from modelguard.core.serialization import canonical_json_bytes, parse_strict_json_bytes
from modelguard.monitoring.events import EventIdentity
from modelguard.storage.publisher import (
    ACTIVE_PARAMETER_NAME,
    PREVIOUS_PARAMETER_NAME,
    PROMOTION_LOCK_KEY,
    CreateOnlyModelBundlePublisher,
    ModelPublicationError,
)
from modelguard.storage.versioned_bundle import (
    ActiveMonitoringPointer,
    VersionedBundleLocation,
)
from modelguard.training.bundle import EXPECTED_FILENAMES

ACCOUNT_ID = "123456789012"
REGION = "us-east-1"
BUCKET = f"modelguard-ai-demo-{ACCOUNT_ID}-{REGION}-models"
UNSET_POINTER = json.dumps(
    {
        "manifest_sha256": "UNSET",
        "model_version": "UNSET",
        "pointer_schema_version": "modelguard.unset.v1",
    },
    separators=(",", ":"),
    sort_keys=True,
)


def _error(code: str, operation: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "sanitized fake"},
            "ResponseMetadata": {"HTTPStatusCode": 412 if code == "PreconditionFailed" else 400},
        },
        operation,
    )


@dataclass
class StoredVersion:
    version_id: str
    payload: bytes
    checksum: str
    content_type: str
    metadata: dict[str, str]
    encryption: str


class S3Double:
    def __init__(self) -> None:
        self.versions: dict[str, list[StoredVersion]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_put_suffix: str | None = None
        self.tamper_read_suffix: str | None = None
        self.version_counter = 0

    def get_bucket_location(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("get_bucket_location", kwargs))
        assert kwargs == {"Bucket": BUCKET, "ExpectedBucketOwner": ACCOUNT_ID}
        return {"LocationConstraint": None}

    def get_bucket_versioning(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("get_bucket_versioning", kwargs))
        assert kwargs == {"Bucket": BUCKET, "ExpectedBucketOwner": ACCOUNT_ID}
        return {"Status": "Enabled"}

    def list_object_versions(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("list_object_versions", kwargs))
        assert kwargs["Bucket"] == BUCKET
        assert kwargs["ExpectedBucketOwner"] == ACCOUNT_ID
        assert kwargs["MaxKeys"] == 1
        prefix = kwargs["Prefix"]
        versions = [
            {"Key": key, "VersionId": stored.version_id}
            for key, history in sorted(self.versions.items())
            if key.startswith(prefix)
            for stored in reversed(history)
        ][:1]
        return {"DeleteMarkers": [], "IsTruncated": False, "Versions": versions}

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("put_object", kwargs))
        assert kwargs["Bucket"] == BUCKET
        assert kwargs["ExpectedBucketOwner"] == ACCOUNT_ID
        assert kwargs["IfNoneMatch"] == "*"
        assert kwargs["ServerSideEncryption"] == "AES256"
        key = kwargs["Key"]
        if self.versions.get(key):
            raise _error("PreconditionFailed", "PutObject")
        if self.fail_put_suffix is not None and key.endswith(self.fail_put_suffix):
            raise _error("InternalError", "PutObject")
        self.version_counter += 1
        version_id = f"version-{self.version_counter:04d}"
        stored = StoredVersion(
            version_id=version_id,
            payload=bytes(kwargs["Body"]),
            checksum=kwargs["ChecksumSHA256"],
            content_type=kwargs["ContentType"],
            metadata=dict(kwargs["Metadata"]),
            encryption=kwargs["ServerSideEncryption"],
        )
        self.versions.setdefault(key, []).append(stored)
        return {
            "ChecksumSHA256": stored.checksum,
            "ServerSideEncryption": stored.encryption,
            "VersionId": version_id,
        }

    def _stored(self, key: str, version_id: str | None = None) -> StoredVersion:
        history = self.versions.get(key, [])
        if version_id is None and history:
            return history[-1]
        for stored in history:
            if stored.version_id == version_id:
                return stored
        raise _error("NoSuchKey", "GetObject")

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("get_object", kwargs))
        assert kwargs["Bucket"] == BUCKET
        assert kwargs["ExpectedBucketOwner"] == ACCOUNT_ID
        assert kwargs["ChecksumMode"] == "ENABLED"
        stored = self._stored(kwargs["Key"], kwargs.get("VersionId"))
        payload = stored.payload
        if self.tamper_read_suffix is not None and kwargs["Key"].endswith(self.tamper_read_suffix):
            payload += b"tampered"
        return {
            "Body": io.BytesIO(payload),
            "ChecksumSHA256": stored.checksum,
            "ContentLength": len(payload),
            "ContentType": stored.content_type,
            "Metadata": stored.metadata,
            "ServerSideEncryption": stored.encryption,
            "VersionId": stored.version_id,
        }

    def head_object(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("head_object", kwargs))
        assert kwargs["Bucket"] == BUCKET
        assert kwargs["ExpectedBucketOwner"] == ACCOUNT_ID
        stored = self._stored(kwargs["Key"])
        return {
            "ChecksumSHA256": stored.checksum,
            "ContentLength": len(stored.payload),
            "ContentType": stored.content_type,
            "Metadata": stored.metadata,
            "ServerSideEncryption": stored.encryption,
            "VersionId": stored.version_id,
        }

    def delete_object(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("delete_object", kwargs))
        assert kwargs["Bucket"] == BUCKET
        assert kwargs["ExpectedBucketOwner"] == ACCOUNT_ID
        key = kwargs["Key"]
        version_id = kwargs["VersionId"]
        history = self.versions.get(key, [])
        self.versions[key] = [item for item in history if item.version_id != version_id]
        if not self.versions[key]:
            del self.versions[key]
        return {"VersionId": version_id}


class SsmDouble:
    def __init__(
        self,
        *,
        active: str = UNSET_POINTER,
        previous: str = UNSET_POINTER,
    ) -> None:
        self.parameters = {
            ACTIVE_PARAMETER_NAME: {"value": active, "version": 1},
            PREVIOUS_PARAMETER_NAME: {"value": previous, "version": 1},
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.failures: dict[str, list[str]] = {}

    def get_parameter(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("get_parameter", kwargs))
        assert kwargs["WithDecryption"] is False
        parameter = self.parameters[kwargs["Name"]]
        return {
            "Parameter": {
                "Name": kwargs["Name"],
                "Type": "String",
                "Value": parameter["value"],
                "Version": parameter["version"],
            }
        }

    def put_parameter(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("put_parameter", kwargs))
        assert kwargs["Type"] == "String"
        assert kwargs["DataType"] == "text"
        assert kwargs["Overwrite"] is True
        name = kwargs["Name"]
        failure = self.failures.get(name, []).pop(0) if self.failures.get(name) else None
        if failure == "before":
            raise _error("InternalServerError", "PutParameter")
        parameter = self.parameters[name]
        parameter["value"] = kwargs["Value"]
        parameter["version"] += 1
        if failure == "after":
            raise _error("InternalServerError", "PutParameter")
        return {"Tier": "Standard", "Version": parameter["version"]}


def _publisher(s3: S3Double, ssm: SsmDouble) -> CreateOnlyModelBundlePublisher:
    return CreateOnlyModelBundlePublisher(
        s3_client=s3,
        ssm_client=ssm,
        bucket=BUCKET,
        expected_account_id=ACCOUNT_ID,
        region=REGION,
        transaction_id_factory=lambda: "a" * 32,
    )


def _model_keys(s3: S3Double) -> list[str]:
    return sorted(key for key in s3.versions if key != PROMOTION_LOCK_KEY)


def _active_pointer(ssm: SsmDouble) -> ActiveMonitoringPointer:
    value = ssm.parameters[ACTIVE_PARAMETER_NAME]["value"]
    assert isinstance(value, str)
    return ActiveMonitoringPointer.model_validate(parse_strict_json_bytes(value.encode("utf-8")))


def _old_pointer() -> str:
    pointer = ActiveMonitoringPointer(
        target_identity=EventIdentity(
            event_schema_version="modelguard.prediction-event.v1",
            model_version="0.9.0",
            bundle_manifest_sha256="f" * 64,
            input_schema_version="modelguard.input.v1",
        ),
        bundle=VersionedBundleLocation(
            bucket=BUCKET,
            key_prefix="model-bundles/0.9.0/",
            object_version_ids={
                name: f"old-{index}" for index, name in enumerate(EXPECTED_FILENAMES)
            },
        ),
    )
    return canonical_json_bytes(pointer).decode("utf-8")


def test_success_is_create_only_version_pinned_and_promotes_active_previous_atomically(
    audited_workspace: Any,
) -> None:
    old_active = _old_pointer()
    s3 = S3Double()
    ssm = SsmDouble(active=old_active)

    result = _publisher(s3, ssm).publish_and_promote(audited_workspace.result.bundle_path)

    assert result.status == "passed"
    assert result.model_version == "1.0.0"
    assert set(result.object_version_ids) == EXPECTED_FILENAMES
    pointer = _active_pointer(ssm)
    assert pointer.target_identity.bundle_manifest_sha256 == result.manifest_sha256
    assert pointer.bundle.object_version_ids == result.object_version_ids
    assert ssm.parameters[PREVIOUS_PARAMETER_NAME]["value"] == old_active
    pointer_writes = [
        arguments["Name"] for operation, arguments in ssm.calls if operation == "put_parameter"
    ]
    assert pointer_writes == [PREVIOUS_PARAMETER_NAME, ACTIVE_PARAMETER_NAME]
    assert PROMOTION_LOCK_KEY not in s3.versions
    assert len(_model_keys(s3)) == 7
    assert _model_keys(s3) == [f"model-bundles/1.0.0/{name}" for name in sorted(EXPECTED_FILENAMES)]
    model_puts = [
        arguments
        for operation, arguments in s3.calls
        if operation == "put_object" and arguments["Key"] != PROMOTION_LOCK_KEY
    ]
    assert len(model_puts) == 7
    assert all(arguments["IfNoneMatch"] == "*" for arguments in model_puts)
    assert model_puts[-1]["Key"].endswith("/checksums.sha256")
    assert not [
        arguments
        for operation, arguments in s3.calls
        if operation == "delete_object" and arguments["Key"] != PROMOTION_LOCK_KEY
    ]
    safe_output = result.model_dump_json()
    assert ACCOUNT_ID not in safe_output
    assert "credential" not in safe_output.casefold()
    assert "secret" not in safe_output.casefold()


def test_corrupt_local_manifest_fails_before_any_cloud_client_call(
    audited_workspace: Any,
    tmp_path: Path,
) -> None:
    bundle = Path(shutil.copytree(audited_workspace.result.bundle_path, tmp_path / "1.0.0"))
    (bundle / "manifest.json").write_bytes((bundle / "manifest.json").read_bytes() + b"corrupt")
    s3 = S3Double()
    ssm = SsmDouble()

    with pytest.raises(ModelPublicationError, match="local_bundle_verification_failed"):
        _publisher(s3, ssm).publish_and_promote(bundle)

    assert s3.calls == []
    assert ssm.calls == []


def test_historical_version_refuses_republication_even_without_a_current_pointer(
    audited_workspace: Any,
) -> None:
    s3 = S3Double()
    stale_key = "model-bundles/1.0.0/manifest.json"
    s3.versions[stale_key] = [
        StoredVersion("historical-1", b"old", "checksum", "application/json", {}, "AES256")
    ]
    ssm = SsmDouble()

    with pytest.raises(ModelPublicationError, match="model_version_already_published"):
        _publisher(s3, ssm).publish_and_promote(audited_workspace.result.bundle_path)

    assert ssm.calls == []
    assert s3.versions[stale_key][0].payload == b"old"
    assert PROMOTION_LOCK_KEY not in s3.versions


def test_partial_upload_is_never_activated_deleted_or_reused(
    audited_workspace: Any,
) -> None:
    s3 = S3Double()
    s3.fail_put_suffix = "/metrics.json"
    ssm = SsmDouble()
    publisher = _publisher(s3, ssm)

    with pytest.raises(ModelPublicationError, match="model_object_write_failed"):
        publisher.publish_and_promote(audited_workspace.result.bundle_path)

    assert ssm.parameters[ACTIVE_PARAMETER_NAME]["value"] == UNSET_POINTER
    assert ssm.parameters[PREVIOUS_PARAMETER_NAME]["value"] == UNSET_POINTER
    assert 1 <= len(_model_keys(s3)) < 7
    assert PROMOTION_LOCK_KEY not in s3.versions
    assert not [
        arguments
        for operation, arguments in s3.calls
        if operation == "delete_object" and arguments["Key"] != PROMOTION_LOCK_KEY
    ]

    s3.fail_put_suffix = None
    with pytest.raises(ModelPublicationError, match="model_version_already_published"):
        publisher.publish_and_promote(audited_workspace.result.bundle_path)
    assert ssm.parameters[ACTIVE_PARAMETER_NAME]["value"] == UNSET_POINTER


def test_readback_byte_mismatch_fails_before_pointer_mutation(
    audited_workspace: Any,
) -> None:
    s3 = S3Double()
    s3.tamper_read_suffix = "/manifest.json"
    ssm = SsmDouble()

    with pytest.raises(ModelPublicationError, match="published_object_byte_mismatch"):
        _publisher(s3, ssm).publish_and_promote(audited_workspace.result.bundle_path)

    assert ssm.parameters[ACTIVE_PARAMETER_NAME]["value"] == UNSET_POINTER
    assert not [call for call in ssm.calls if call[0] == "put_parameter"]


def test_existing_conditional_lock_serializes_concurrent_publishers(
    audited_workspace: Any,
) -> None:
    s3 = S3Double()
    s3.versions[PROMOTION_LOCK_KEY] = [
        StoredVersion(
            "other-lock",
            b"other",
            "checksum",
            "application/json",
            {"lock-sha256": sha256_bytes(b"other")},
            "AES256",
        )
    ]
    ssm = SsmDouble()

    with pytest.raises(ModelPublicationError, match="promotion_lock_busy"):
        _publisher(s3, ssm).publish_and_promote(audited_workspace.result.bundle_path)

    assert ssm.calls == []
    assert _model_keys(s3) == []
    assert s3.versions[PROMOTION_LOCK_KEY][0].version_id == "other-lock"


def test_active_write_after_server_failure_rolls_both_pointers_back_and_releases_lock(
    audited_workspace: Any,
) -> None:
    old_active = _old_pointer()
    old_previous = UNSET_POINTER
    s3 = S3Double()
    ssm = SsmDouble(active=old_active, previous=old_previous)
    ssm.failures[ACTIVE_PARAMETER_NAME] = ["after"]

    with pytest.raises(ModelPublicationError, match="model_pointer_write_failed"):
        _publisher(s3, ssm).publish_and_promote(audited_workspace.result.bundle_path)

    assert ssm.parameters[ACTIVE_PARAMETER_NAME]["value"] == old_active
    assert ssm.parameters[PREVIOUS_PARAMETER_NAME]["value"] == old_previous
    assert PROMOTION_LOCK_KEY not in s3.versions
    assert len(_model_keys(s3)) == 7


def test_unprovable_pointer_rollback_retains_lock_and_blocks_follow_up(
    audited_workspace: Any,
) -> None:
    old_active = _old_pointer()
    s3 = S3Double()
    ssm = SsmDouble(active=old_active)
    ssm.failures[ACTIVE_PARAMETER_NAME] = ["after", "before"]
    publisher = _publisher(s3, ssm)

    with pytest.raises(ModelPublicationError, match="model_pointer_rollback_failed") as failure:
        publisher.publish_and_promote(audited_workspace.result.bundle_path)

    assert failure.value.retain_lock is True
    assert PROMOTION_LOCK_KEY in s3.versions
    assert ssm.parameters[PREVIOUS_PARAMETER_NAME]["value"] == old_active
    with pytest.raises(ModelPublicationError, match="promotion_lock_busy"):
        publisher.publish_and_promote(audited_workspace.result.bundle_path)


def test_cli_accepts_no_credential_secret_or_local_output_value_arguments() -> None:
    help_text = _parser().format_help()

    for forbidden in (
        "--access-key",
        "--secret-key",
        "--session-token",
        "--token",
        "--password",
        "--output",
    ):
        assert forbidden not in help_text
    assert "--profile" in help_text
    assert "--workflow-role-arn" in help_text
    assert "--confirmation" in help_text


def test_cli_rejects_bad_local_bundle_before_constructing_an_aws_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden_session(**kwargs: Any) -> None:
        del kwargs
        raise AssertionError("AWS session must not be constructed for a bad local bundle")

    monkeypatch.setattr(model_bundle_publisher.boto3, "Session", forbidden_session)
    monkeypatch.setattr(
        "sys.argv",
        [
            "model-bundle-publisher",
            "publish-and-promote",
            "--bundle",
            str(tmp_path / "missing"),
            "--expected-account-id",
            ACCOUNT_ID,
            "--region",
            REGION,
            "--profile",
            "modelguard-bootstrap",
            "--confirmation",
            model_bundle_publisher.PUBLISH_CONFIRMATION,
        ],
    )

    assert model_bundle_publisher.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "reason": "local_bundle_verification_failed",
        "status": "refused",
    }
