"""Create-only S3 model publication with serialized, rollback-safe SSM promotion."""

from __future__ import annotations

import base64
import re
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from uuid import uuid4

from botocore.exceptions import ClientError
from pydantic import Field, model_validator

from modelguard.core.hashing import sha256_bytes
from modelguard.core.serialization import (
    StrictArtifactModel,
    canonical_json_bytes,
    parse_strict_json_bytes,
    validate_strict_json_model,
)
from modelguard.monitoring.events import target_identity_from_bundle
from modelguard.storage.versioned_bundle import (
    BUNDLE_OBJECT_MAX_BYTES,
    ActiveMonitoringPointer,
    ReadableBody,
    VersionedBundleLocation,
    validate_pointer_scope,
    verify_model_joblib_memory_bound,
)
from modelguard.training.bundle import (
    CHECKSUM_FILENAME,
    EXPECTED_FILENAMES,
    inspect_bundle,
)

CANONICAL_REGION = "us-east-1"
ACTIVE_PARAMETER_NAME = "/modelguard-ai/demo/models/active"
PREVIOUS_PARAMETER_NAME = "/modelguard-ai/demo/models/previous"
PROMOTION_LOCK_KEY = "model-bundles/.modelguard-promotion.lock"
MAX_POINTER_BYTES = 4 * 1024
VERSION_ID_PATTERN = re.compile(r"^[^\x00-\x1f\x7f]{1,1024}$")


class ModelPublicationError(RuntimeError):
    """A bounded refusal that is safe to return without cloud exception details."""

    def __init__(self, reason: str, *, retain_lock: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retain_lock = retain_lock


class UnsetModelPointer(StrictArtifactModel):
    """Exact Terraform-created sentinel accepted before the first promotion."""

    pointer_schema_version: Literal["modelguard.unset.v1"]
    model_version: Literal["UNSET"]
    manifest_sha256: Literal["UNSET"]


class PublicationResult(StrictArtifactModel):
    """Non-secret identities needed by the later activation-plan review."""

    status: Literal["passed"] = "passed"
    model_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pointer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    object_version_ids: dict[str, str]
    active_parameter_name: Literal["/modelguard-ai/demo/models/active"] = (
        "/modelguard-ai/demo/models/active"
    )
    previous_parameter_name: Literal["/modelguard-ai/demo/models/previous"] = (
        "/modelguard-ai/demo/models/previous"
    )

    @model_validator(mode="after")
    def validate_exact_versions(self) -> PublicationResult:
        if set(self.object_version_ids) != EXPECTED_FILENAMES:
            raise ValueError("publication result must include all seven object VersionIds")
        if not all(
            VERSION_ID_PATTERN.fullmatch(value) for value in self.object_version_ids.values()
        ):
            raise ValueError("publication result contains an invalid object VersionId")
        return self


class ModelObjectClient(Protocol):
    """Narrow S3 boundary used by publication and its global promotion lock."""

    def get_bucket_location(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_bucket_versioning(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def list_object_versions(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def head_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def delete_object(self, **kwargs: Any) -> Mapping[str, Any]: ...


class ModelPointerClient(Protocol):
    """Narrow SSM boundary used for active/previous pointer snapshots and writes."""

    def get_parameter(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def put_parameter(self, **kwargs: Any) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ParameterSnapshot:
    name: str
    version: int
    digest: str
    value: str = field(repr=False)


@dataclass(frozen=True)
class LockLease:
    version_id: str
    checksum_sha256: str
    body: bytes = field(repr=False)


def _client_error_code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))


def _checksum_base64(payload: bytes) -> str:
    return base64.b64encode(bytes.fromhex(sha256_bytes(payload))).decode("ascii")


def _content_type(filename: str) -> str:
    if filename.endswith(".json"):
        return "application/json"
    if filename == CHECKSUM_FILENAME:
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def _bounded_response_body(response: Mapping[str, Any], *, maximum_bytes: int) -> bytes:
    content_length = response.get("ContentLength")
    if not isinstance(content_length, int) or not 0 <= content_length <= maximum_bytes:
        raise ModelPublicationError("published_object_response_invalid")
    body = response.get("Body")
    if body is None or not hasattr(body, "read"):
        raise ModelPublicationError("published_object_response_invalid")
    reader = cast(ReadableBody, body)
    try:
        payload = reader.read(maximum_bytes + 1)
    finally:
        with suppress(AttributeError, OSError):
            reader.close()
    if not isinstance(payload, bytes) or len(payload) != content_length:
        raise ModelPublicationError("published_object_response_invalid")
    if len(payload) > maximum_bytes:
        raise ModelPublicationError("published_object_too_large")
    return payload


class CreateOnlyModelBundlePublisher:
    """Publish one never-before-used version, then transactionally promote its pointer."""

    def __init__(
        self,
        *,
        s3_client: ModelObjectClient,
        ssm_client: ModelPointerClient,
        bucket: str,
        expected_account_id: str,
        region: str,
        transaction_id_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        expected_bucket = f"modelguard-ai-demo-{expected_account_id}-{region}-models"
        if re.fullmatch(r"[0-9]{12}", expected_account_id) is None:
            raise ValueError("expected AWS account ID must contain twelve digits")
        if region != CANONICAL_REGION:
            raise ValueError("model publication is restricted to the canonical Region")
        if bucket != expected_bucket:
            raise ValueError("model publication bucket does not match account and Region")
        self._s3 = s3_client
        self._ssm = ssm_client
        self._bucket = bucket
        self._account_id = expected_account_id
        self._region = region
        self._transaction_id_factory = transaction_id_factory

    def publish_and_promote(self, bundle_path: Path) -> PublicationResult:
        """Verify locally, publish seven immutable versions, verify bytes, and promote last."""

        try:
            metadata = inspect_bundle(bundle_path)
            verify_model_joblib_memory_bound(bundle_path / "model.joblib")
            if bundle_path.name != metadata.identity.model_version:
                raise ValueError("bundle directory name differs from its semantic version")
            payloads = self._read_bounded_payloads(bundle_path)
        except (OSError, ValueError) as error:
            raise ModelPublicationError("local_bundle_verification_failed") from error

        self._require_bucket_contract()
        lease: LockLease | None = None
        release_lock = True
        try:
            lease = self._acquire_lock(
                model_version=metadata.identity.model_version,
                manifest_sha256=metadata.identity.manifest_sha256,
            )
            prefix = f"model-bundles/{metadata.identity.model_version}/"
            self._require_never_used_prefix(prefix)
            active_snapshot = self._snapshot_parameter(ACTIVE_PARAMETER_NAME)
            previous_snapshot = self._snapshot_parameter(PREVIOUS_PARAMETER_NAME)
            version_ids = self._publish_and_verify_objects(
                prefix=prefix,
                model_version=metadata.identity.model_version,
                payloads=payloads,
            )
            pointer = ActiveMonitoringPointer(
                target_identity=target_identity_from_bundle(metadata),
                bundle=VersionedBundleLocation(
                    bucket=self._bucket,
                    key_prefix=prefix,
                    object_version_ids=version_ids,
                ),
            )
            pointer_value = canonical_json_bytes(pointer).decode("utf-8")
            if len(pointer_value.encode("utf-8")) > MAX_POINTER_BYTES:
                raise ModelPublicationError("active_pointer_too_large")
            self._promote_pointer(
                pointer_value=pointer_value,
                active_snapshot=active_snapshot,
                previous_snapshot=previous_snapshot,
            )
            return PublicationResult(
                model_version=metadata.identity.model_version,
                manifest_sha256=metadata.identity.manifest_sha256,
                pointer_sha256=sha256_bytes(pointer_value.encode("utf-8")),
                object_version_ids=version_ids,
            )
        except ModelPublicationError as error:
            release_lock = not error.retain_lock
            raise
        except (ClientError, OSError, ValueError) as error:
            raise ModelPublicationError("model_publication_failed") from error
        finally:
            if lease is not None and release_lock:
                self._release_lock(lease)

    def _read_bounded_payloads(self, bundle_path: Path) -> dict[str, bytes]:
        payloads: dict[str, bytes] = {}
        for filename in sorted(EXPECTED_FILENAMES):
            payload = (bundle_path / filename).read_bytes()
            if not payload or len(payload) > BUNDLE_OBJECT_MAX_BYTES[filename]:
                raise ValueError(f"bundle object violates its size contract: {filename}")
            payloads[filename] = payload
        return payloads

    def _require_bucket_contract(self) -> None:
        try:
            location = self._s3.get_bucket_location(
                Bucket=self._bucket,
                ExpectedBucketOwner=self._account_id,
            )
            versioning = self._s3.get_bucket_versioning(
                Bucket=self._bucket,
                ExpectedBucketOwner=self._account_id,
            )
        except ClientError as error:
            raise ModelPublicationError("model_bucket_preflight_failed") from error
        if (
            "LocationConstraint" not in location
            or location["LocationConstraint"] is not None
            or self._region != "us-east-1"
        ):
            raise ModelPublicationError("model_bucket_region_mismatch")
        if versioning.get("Status") != "Enabled":
            raise ModelPublicationError("model_bucket_versioning_required")

    def _acquire_lock(self, *, model_version: str, manifest_sha256: str) -> LockLease:
        transaction_id = self._transaction_id_factory()
        if re.fullmatch(r"[0-9a-f]{32}", transaction_id) is None:
            raise ModelPublicationError("promotion_transaction_identity_invalid")
        body = canonical_json_bytes(
            {
                "lock_schema_version": "modelguard.model-promotion-lock.v1",
                "target_manifest_sha256": manifest_sha256,
                "target_model_version": model_version,
                "transaction_id": transaction_id,
            }
        )
        checksum = _checksum_base64(body)
        try:
            response = self._s3.put_object(
                Bucket=self._bucket,
                Key=PROMOTION_LOCK_KEY,
                Body=body,
                ContentType="application/json",
                ChecksumSHA256=checksum,
                ExpectedBucketOwner=self._account_id,
                IfNoneMatch="*",
                Metadata={"lock-sha256": sha256_bytes(body)},
                ServerSideEncryption="AES256",
            )
        except ClientError as error:
            if _client_error_code(error) in {
                "ConditionalRequestConflict",
                "PreconditionFailed",
                "412",
            }:
                raise ModelPublicationError("promotion_lock_busy") from error
            raise ModelPublicationError("promotion_lock_acquisition_failed") from error
        version_id = response.get("VersionId")
        if (
            not isinstance(version_id, str)
            or VERSION_ID_PATTERN.fullmatch(version_id) is None
            or response.get("ChecksumSHA256") != checksum
            or response.get("ServerSideEncryption") != "AES256"
        ):
            raise ModelPublicationError(
                "promotion_lock_response_invalid",
                retain_lock=isinstance(version_id, str),
            )
        lease = LockLease(version_id=version_id, checksum_sha256=checksum, body=body)
        try:
            self._verify_lock(lease)
        except ModelPublicationError as error:
            try:
                self._release_lock(lease)
            except ModelPublicationError as release_error:
                raise ModelPublicationError(
                    "promotion_lock_verification_and_release_failed",
                    retain_lock=True,
                ) from release_error
            raise error
        return lease

    def _verify_lock(self, lease: LockLease) -> None:
        try:
            head = self._s3.head_object(
                Bucket=self._bucket,
                Key=PROMOTION_LOCK_KEY,
                ChecksumMode="ENABLED",
                ExpectedBucketOwner=self._account_id,
            )
            response = self._s3.get_object(
                Bucket=self._bucket,
                Key=PROMOTION_LOCK_KEY,
                VersionId=lease.version_id,
                ChecksumMode="ENABLED",
                ExpectedBucketOwner=self._account_id,
            )
        except ClientError as error:
            raise ModelPublicationError("promotion_lock_verification_failed") from error
        expected_metadata = {"lock-sha256": sha256_bytes(lease.body)}
        for candidate in (head, response):
            if (
                candidate.get("VersionId") != lease.version_id
                or candidate.get("ChecksumSHA256") != lease.checksum_sha256
                or candidate.get("ServerSideEncryption") != "AES256"
                or candidate.get("Metadata") != expected_metadata
                or candidate.get("ContentLength") != len(lease.body)
            ):
                raise ModelPublicationError("promotion_lock_verification_failed")
        if _bounded_response_body(response, maximum_bytes=4 * 1024) != lease.body:
            raise ModelPublicationError("promotion_lock_verification_failed")

    def _release_lock(self, lease: LockLease) -> None:
        try:
            current = self._s3.head_object(
                Bucket=self._bucket,
                Key=PROMOTION_LOCK_KEY,
                ExpectedBucketOwner=self._account_id,
            )
            if current.get("VersionId") != lease.version_id:
                raise ModelPublicationError(
                    "promotion_lock_ownership_lost",
                    retain_lock=True,
                )
            response = self._s3.delete_object(
                Bucket=self._bucket,
                Key=PROMOTION_LOCK_KEY,
                VersionId=lease.version_id,
                ExpectedBucketOwner=self._account_id,
            )
            if response.get("VersionId") != lease.version_id:
                raise ModelPublicationError(
                    "promotion_lock_release_failed",
                    retain_lock=True,
                )
            try:
                self._s3.head_object(
                    Bucket=self._bucket,
                    Key=PROMOTION_LOCK_KEY,
                    ExpectedBucketOwner=self._account_id,
                )
            except ClientError as error:
                if _client_error_code(error) in {"404", "NoSuchKey", "NotFound"}:
                    return
                raise
            raise ModelPublicationError(
                "promotion_lock_release_failed",
                retain_lock=True,
            )
        except ModelPublicationError:
            raise
        except ClientError as error:
            raise ModelPublicationError(
                "promotion_lock_release_failed",
                retain_lock=True,
            ) from error

    def _require_never_used_prefix(self, prefix: str) -> None:
        try:
            response = self._s3.list_object_versions(
                Bucket=self._bucket,
                Prefix=prefix,
                MaxKeys=1,
                ExpectedBucketOwner=self._account_id,
            )
        except ClientError as error:
            raise ModelPublicationError("model_version_history_check_failed") from error
        versions = response.get("Versions", [])
        delete_markers = response.get("DeleteMarkers", [])
        if not isinstance(versions, list) or not isinstance(delete_markers, list):
            raise ModelPublicationError("model_version_history_response_invalid")
        if versions or delete_markers:
            raise ModelPublicationError("model_version_already_published")
        if response.get("IsTruncated") is not False:
            raise ModelPublicationError("model_version_history_response_invalid")

    def _publish_and_verify_objects(
        self,
        *,
        prefix: str,
        model_version: str,
        payloads: Mapping[str, bytes],
    ) -> dict[str, str]:
        version_ids: dict[str, str] = {}
        ordered_filenames = [
            *sorted(EXPECTED_FILENAMES - {CHECKSUM_FILENAME}),
            CHECKSUM_FILENAME,
        ]
        for filename in ordered_filenames:
            payload = payloads[filename]
            digest = sha256_bytes(payload)
            checksum = _checksum_base64(payload)
            key = f"{prefix}{filename}"
            metadata = {"model-version": model_version, "sha256": digest}
            try:
                response = self._s3.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=payload,
                    ContentType=_content_type(filename),
                    ChecksumSHA256=checksum,
                    ExpectedBucketOwner=self._account_id,
                    IfNoneMatch="*",
                    Metadata=metadata,
                    ServerSideEncryption="AES256",
                )
            except ClientError as error:
                reason = (
                    "model_object_collision"
                    if _client_error_code(error)
                    in {"ConditionalRequestConflict", "PreconditionFailed", "412"}
                    else "model_object_write_failed"
                )
                raise ModelPublicationError(reason) from error
            version_id = response.get("VersionId")
            if (
                not isinstance(version_id, str)
                or VERSION_ID_PATTERN.fullmatch(version_id) is None
                or response.get("ChecksumSHA256") != checksum
                or response.get("ServerSideEncryption") != "AES256"
            ):
                raise ModelPublicationError("model_object_write_response_invalid")
            self._verify_published_object(
                key=key,
                filename=filename,
                version_id=version_id,
                checksum=checksum,
                metadata=metadata,
                expected_payload=payload,
            )
            version_ids[filename] = version_id
        return version_ids

    def _verify_published_object(
        self,
        *,
        key: str,
        filename: str,
        version_id: str,
        checksum: str,
        metadata: Mapping[str, str],
        expected_payload: bytes,
    ) -> None:
        try:
            response = self._s3.get_object(
                Bucket=self._bucket,
                Key=key,
                VersionId=version_id,
                ChecksumMode="ENABLED",
                ExpectedBucketOwner=self._account_id,
            )
        except ClientError as error:
            raise ModelPublicationError("published_object_readback_failed") from error
        if (
            response.get("VersionId") != version_id
            or response.get("ChecksumSHA256") != checksum
            or response.get("ServerSideEncryption") != "AES256"
            or response.get("Metadata") != metadata
            or response.get("ContentType") != _content_type(filename)
        ):
            raise ModelPublicationError("published_object_identity_mismatch")
        actual_payload = _bounded_response_body(
            response,
            maximum_bytes=BUNDLE_OBJECT_MAX_BYTES[filename],
        )
        if actual_payload != expected_payload:
            raise ModelPublicationError("published_object_byte_mismatch")

    def _snapshot_parameter(self, name: str) -> ParameterSnapshot:
        try:
            response = self._ssm.get_parameter(Name=name, WithDecryption=False)
        except ClientError as error:
            raise ModelPublicationError("model_pointer_read_failed") from error
        parameter = response.get("Parameter")
        if not isinstance(parameter, Mapping):
            raise ModelPublicationError("model_pointer_response_invalid")
        value = parameter.get("Value")
        version = parameter.get("Version")
        if (
            parameter.get("Name") != name
            or parameter.get("Type") != "String"
            or not isinstance(value, str)
            or not isinstance(version, int)
            or isinstance(version, bool)
            or version < 1
            or len(value.encode("utf-8")) > MAX_POINTER_BYTES
        ):
            raise ModelPublicationError("model_pointer_response_invalid")
        self._validate_pointer_value(value)
        return ParameterSnapshot(
            name=name,
            version=version,
            digest=sha256_bytes(value.encode("utf-8")),
            value=value,
        )

    def _validate_pointer_value(self, value: str) -> None:
        try:
            parsed = parse_strict_json_bytes(value.encode("utf-8"))
            if not isinstance(parsed, Mapping):
                raise ValueError("pointer must be a JSON object")
            schema = parsed.get("pointer_schema_version")
            if schema == "modelguard.unset.v1":
                validate_strict_json_model(value.encode("utf-8"), UnsetModelPointer)
                return
            if schema != "modelguard.active-monitor-target.v1":
                raise ValueError("pointer schema is not approved")
            pointer = validate_strict_json_model(value.encode("utf-8"), ActiveMonitoringPointer)
            model_version = pointer.target_identity.model_version
            validate_pointer_scope(
                pointer,
                expected_bucket=self._bucket,
                expected_model_version=model_version,
            )
            if (
                pointer.target_identity.event_schema_version != "modelguard.prediction-event.v1"
                or pointer.target_identity.input_schema_version != "modelguard.input.v1"
                or not all(
                    VERSION_ID_PATTERN.fullmatch(version_id)
                    for version_id in pointer.bundle.object_version_ids.values()
                )
            ):
                raise ValueError("pointer identity does not match the v1 runtime contract")
        except ValueError as error:
            raise ModelPublicationError("model_pointer_value_invalid") from error

    def _require_snapshot_unchanged(self, expected: ParameterSnapshot) -> None:
        current = self._snapshot_parameter(expected.name)
        if (
            current.version != expected.version
            or current.digest != expected.digest
            or current.value != expected.value
        ):
            raise ModelPublicationError("model_pointer_concurrency_conflict")

    def _put_and_verify_parameter(
        self,
        *,
        name: str,
        value: str,
        minimum_version: int,
    ) -> ParameterSnapshot:
        try:
            response = self._ssm.put_parameter(
                Name=name,
                Value=value,
                Type="String",
                DataType="text",
                Overwrite=True,
            )
        except ClientError as error:
            raise ModelPublicationError("model_pointer_write_failed") from error
        version = response.get("Version")
        if not isinstance(version, int) or isinstance(version, bool) or version <= minimum_version:
            raise ModelPublicationError("model_pointer_write_response_invalid")
        observed = self._snapshot_parameter(name)
        if observed.version != version or observed.value != value:
            raise ModelPublicationError("model_pointer_write_verification_failed")
        return observed

    def _promote_pointer(
        self,
        *,
        pointer_value: str,
        active_snapshot: ParameterSnapshot,
        previous_snapshot: ParameterSnapshot,
    ) -> None:
        active_attempted = False
        previous_attempted = False
        try:
            self._require_snapshot_unchanged(active_snapshot)
            self._require_snapshot_unchanged(previous_snapshot)
            previous_attempted = True
            promoted_previous = self._put_and_verify_parameter(
                name=PREVIOUS_PARAMETER_NAME,
                value=active_snapshot.value,
                minimum_version=previous_snapshot.version,
            )
            self._require_snapshot_unchanged(active_snapshot)
            active_attempted = True
            promoted_active = self._put_and_verify_parameter(
                name=ACTIVE_PARAMETER_NAME,
                value=pointer_value,
                minimum_version=active_snapshot.version,
            )
            final_active = self._snapshot_parameter(ACTIVE_PARAMETER_NAME)
            final_previous = self._snapshot_parameter(PREVIOUS_PARAMETER_NAME)
            if (
                final_active != promoted_active
                or final_previous != promoted_previous
                or final_active.value != pointer_value
                or final_previous.value != active_snapshot.value
            ):
                raise ModelPublicationError("model_pointer_final_verification_failed")
        except BaseException as error:
            try:
                self._rollback_pointers(
                    active_snapshot=active_snapshot,
                    previous_snapshot=previous_snapshot,
                    active_attempted=active_attempted,
                    previous_attempted=previous_attempted,
                )
            except BaseException as rollback_error:
                raise ModelPublicationError(
                    "model_pointer_rollback_failed",
                    retain_lock=True,
                ) from rollback_error
            if isinstance(error, ModelPublicationError):
                raise error
            raise ModelPublicationError("model_pointer_promotion_interrupted") from error

    def _rollback_pointers(
        self,
        *,
        active_snapshot: ParameterSnapshot,
        previous_snapshot: ParameterSnapshot,
        active_attempted: bool,
        previous_attempted: bool,
    ) -> None:
        if active_attempted:
            self._put_and_verify_parameter(
                name=ACTIVE_PARAMETER_NAME,
                value=active_snapshot.value,
                minimum_version=active_snapshot.version,
            )
        if previous_attempted:
            self._put_and_verify_parameter(
                name=PREVIOUS_PARAMETER_NAME,
                value=previous_snapshot.value,
                minimum_version=previous_snapshot.version,
            )
        active_after = self._snapshot_parameter(ACTIVE_PARAMETER_NAME)
        previous_after = self._snapshot_parameter(PREVIOUS_PARAMETER_NAME)
        if (
            active_after.value != active_snapshot.value
            or previous_after.value != previous_snapshot.value
        ):
            raise ModelPublicationError("model_pointer_rollback_verification_failed")
