"""Fail-closed SSM/S3 model-bundle hydration with atomic local installation."""

from __future__ import annotations

import os
import shutil
import tempfile
import zlib
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from pydantic import Field, model_validator

from modelguard.core.serialization import StrictArtifactModel, parse_strict_json_bytes
from modelguard.monitoring.events import EventIdentity, verify_target_identity
from modelguard.training.bundle import (
    BASELINE_FILENAME,
    CHECKSUM_FILENAME,
    EXPECTED_FILENAMES,
    MANIFEST_FILENAME,
    METRICS_FILENAME,
    MODEL_FILENAME,
    SCHEMA_FILENAME,
    THRESHOLD_FILENAME,
    ValidatedBundleMetadata,
    inspect_bundle,
)

MODEL_JOBLIB_COMPRESSED_MAX_BYTES = 64 * 1024
MODEL_JOBLIB_DECOMPRESSED_MAX_BYTES = 4 * 1024 * 1024

# These per-object bounds are derived from the reviewed Phase 02 bundle: model.joblib=4,733,
# manifest.json=20,133, input_schema.json=2,279, metrics.json=183,619,
# threshold.json=1,375, baseline_profile.json=40,618, and checksums.sha256=491 bytes. The
# deliberately rounded ceilings allow reviewed metadata growth while bounding the complete
# compressed download to less than 1.25 MiB and model inflation to 4 MiB inside the 1 GiB API task.
BUNDLE_OBJECT_MAX_BYTES: dict[str, int] = {
    MODEL_FILENAME: MODEL_JOBLIB_COMPRESSED_MAX_BYTES,
    MANIFEST_FILENAME: 256 * 1024,
    SCHEMA_FILENAME: 64 * 1024,
    METRICS_FILENAME: 512 * 1024,
    THRESHOLD_FILENAME: 64 * 1024,
    BASELINE_FILENAME: 256 * 1024,
    CHECKSUM_FILENAME: 16 * 1024,
}


def verify_model_joblib_memory_bound(path: Path) -> int:
    """Bound the approved zlib joblib stream before trusted deserialization can occur."""

    payload = path.read_bytes()
    if not payload or len(payload) > MODEL_JOBLIB_COMPRESSED_MAX_BYTES:
        raise ValueError("model.joblib exceeds its measured compressed-size contract")
    inflater = zlib.decompressobj()
    try:
        decompressed = inflater.decompress(payload, MODEL_JOBLIB_DECOMPRESSED_MAX_BYTES + 1)
        if len(decompressed) > MODEL_JOBLIB_DECOMPRESSED_MAX_BYTES or inflater.unconsumed_tail:
            raise ValueError("model.joblib exceeds its bounded decompression-memory contract")
        remaining = MODEL_JOBLIB_DECOMPRESSED_MAX_BYTES + 1 - len(decompressed)
        trailer = inflater.flush(remaining)
    except zlib.error as error:
        raise ValueError("model.joblib is not the approved zlib-compressed stream") from error
    total = len(decompressed) + len(trailer)
    if total > MODEL_JOBLIB_DECOMPRESSED_MAX_BYTES or not inflater.eof or inflater.unused_data:
        raise ValueError("model.joblib compressed stream is incomplete, concatenated, or oversized")
    return total


class SsmPointerClient(Protocol):
    def get_parameter(self, **kwargs: Any) -> Mapping[str, Any]: ...


class VersionedObjectClient(Protocol):
    def get_bucket_location(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]: ...


class ReadableBody(Protocol):
    def read(self, amount: int = -1) -> bytes: ...

    def close(self) -> None: ...


class VersionedBundleLocation(StrictArtifactModel):
    """Every object identity required to reconstruct one immutable bundle."""

    bucket: str = Field(min_length=3, max_length=63, pattern=r"^[a-z0-9][a-z0-9.-]+[a-z0-9]$")
    key_prefix: str = Field(min_length=1, max_length=512)
    object_version_ids: dict[str, str]

    @model_validator(mode="after")
    def validate_exact_bundle(self) -> VersionedBundleLocation:
        if set(self.object_version_ids) != EXPECTED_FILENAMES:
            raise ValueError("AWS bundle pointer must version every exact bundle object")
        if not all(1 <= len(value) <= 1_024 for value in self.object_version_ids.values()):
            raise ValueError("AWS bundle VersionIds cannot be empty or oversized")
        if (
            not self.key_prefix.endswith("/")
            or self.key_prefix.startswith("/")
            or ".." in self.key_prefix.split("/")
            or "//" in self.key_prefix
            or any(ord(character) < 32 for character in self.key_prefix)
        ):
            raise ValueError("bundle key prefix must be a safe relative prefix ending in slash")
        return self


class ActiveMonitoringPointer(StrictArtifactModel):
    """The exact model and object tuple snapshotted from SSM once per process/run."""

    pointer_schema_version: Literal["modelguard.active-monitor-target.v1"] = (
        "modelguard.active-monitor-target.v1"
    )
    target_identity: EventIdentity
    bundle: VersionedBundleLocation


class SsmTargetSnapshotResolver:
    """Read and strictly validate the active target once, without decrypting secrets."""

    def __init__(self, client: SsmPointerClient, *, parameter_name: str) -> None:
        if (
            not parameter_name.startswith("/")
            or len(parameter_name) > 1_011
            or "//" in parameter_name
            or any(ord(character) < 33 for character in parameter_name)
        ):
            raise ValueError("SSM active target parameter name is invalid")
        self._client = client
        self._parameter_name = parameter_name
        self._snapshot: ActiveMonitoringPointer | None = None

    def resolve_once(self) -> ActiveMonitoringPointer:
        if self._snapshot is None:
            response = self._client.get_parameter(
                Name=self._parameter_name,
                WithDecryption=False,
            )
            parameter = response.get("Parameter")
            if (
                not isinstance(parameter, Mapping)
                or parameter.get("Name") != self._parameter_name
                or parameter.get("Type") != "String"
                or not isinstance(parameter.get("Version"), int)
                or parameter["Version"] < 1
                or not isinstance(parameter.get("Value"), str)
            ):
                raise ValueError("SSM active target response lacks a string pointer value")
            value = parameter["Value"]
            if len(value.encode("utf-8")) > 64 * 1024:
                raise ValueError("SSM active target pointer exceeds the size limit")
            self._snapshot = ActiveMonitoringPointer.model_validate(
                parse_strict_json_bytes(value.encode("utf-8"))
            )
        return self._snapshot


def require_exact_bucket_region(
    client: VersionedObjectClient,
    *,
    bucket: str,
    expected_region: str,
) -> None:
    """Prove the configured bucket Region before any versioned object is read."""

    response = client.get_bucket_location(Bucket=bucket)
    if "LocationConstraint" not in response:
        raise ValueError("S3 bucket location response is missing LocationConstraint")
    location = response["LocationConstraint"]
    actual_region = (
        "us-east-1" if location is None else "eu-west-1" if location == "EU" else location
    )
    if not isinstance(actual_region, str) or actual_region != expected_region:
        raise ValueError("S3 model bucket is malformed or in a different Region")


def validate_pointer_scope(
    pointer: ActiveMonitoringPointer,
    *,
    expected_bucket: str,
    expected_model_version: str,
) -> None:
    """Reject bucket, prefix, and model-identity substitution before any S3 read."""

    expected_prefix = f"model-bundles/{expected_model_version}/"
    if pointer.bundle.bucket != expected_bucket:
        raise ValueError("active model pointer bucket does not match runtime configuration")
    if pointer.bundle.key_prefix != expected_prefix:
        raise ValueError("active model pointer prefix does not match the expected model version")
    if pointer.target_identity.model_version != expected_model_version:
        raise ValueError("active model target identity does not match the expected model version")


def _bounded_body_bytes(response: Mapping[str, Any], *, maximum_bytes: int) -> bytes:
    content_length = response.get("ContentLength")
    if not isinstance(content_length, int) or not 0 <= content_length <= maximum_bytes:
        raise ValueError("versioned S3 object has a missing or invalid ContentLength")
    body = response.get("Body")
    if body is None or not hasattr(body, "read"):
        raise ValueError("versioned S3 object response lacks a readable body")
    reader = cast(ReadableBody, body)
    try:
        payload = reader.read(maximum_bytes + 1)
    finally:
        with suppress(AttributeError, OSError):
            reader.close()
    if not isinstance(payload, bytes):
        raise ValueError("versioned S3 object body did not return bytes")
    if len(payload) != content_length or len(payload) > maximum_bytes:
        raise ValueError("versioned S3 object body length does not match its bounded identity")
    return payload


def _create_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("versioned bundle download made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def download_versioned_bundle(
    client: VersionedObjectClient,
    pointer: ActiveMonitoringPointer,
    destination: Path,
) -> ValidatedBundleMetadata:
    """Download exact VersionIds and validate all bytes before any deserialization."""

    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        for filename in sorted(EXPECTED_FILENAMES):
            expected_version_id = pointer.bundle.object_version_ids[filename]
            response = client.get_object(
                Bucket=pointer.bundle.bucket,
                Key=f"{pointer.bundle.key_prefix}{filename}",
                VersionId=expected_version_id,
            )
            if response.get("VersionId") != expected_version_id:
                raise ValueError(
                    "versioned S3 response identity differs from the requested VersionId"
                )
            payload = _bounded_body_bytes(
                response,
                maximum_bytes=BUNDLE_OBJECT_MAX_BYTES[filename],
            )
            _create_file(destination / filename, payload)
        _fsync_directory(destination)
        verify_model_joblib_memory_bound(destination / MODEL_FILENAME)
        metadata = inspect_bundle(destination)
        verify_target_identity(metadata, pointer.target_identity)
        return metadata
    except BaseException:
        # Cleanup also covers process interruption. The exception is re-raised unchanged.
        with suppress(OSError):
            shutil.rmtree(destination)
        raise


@dataclass(frozen=True)
class InstalledBundle:
    path: Path
    metadata: ValidatedBundleMetadata
    reused_existing: bool


class AtomicVersionedBundleInstaller:
    """Hydrate once into a same-filesystem staging directory and publish by rename."""

    def __init__(self, client: VersionedObjectClient) -> None:
        self._client = client

    def install(
        self,
        pointer: ActiveMonitoringPointer,
        *,
        destination: Path,
        expected_bucket: str,
        expected_model_version: str,
    ) -> InstalledBundle:
        validate_pointer_scope(
            pointer,
            expected_bucket=expected_bucket,
            expected_model_version=expected_model_version,
        )
        parent = destination.parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if parent.is_symlink() or not parent.is_dir():
            raise OSError("bundle installation parent must be a non-symlink directory")
        if destination.is_symlink():
            raise OSError("bundle destination must not be a symbolic link")
        if destination.exists():
            raise FileExistsError(
                "bundle destination already exists without exact current-pointer provenance"
            )

        staging_root = Path(tempfile.mkdtemp(prefix=f".{destination.name}.hydrate-", dir=parent))
        staged_bundle = staging_root / "bundle"
        published = False
        try:
            download_versioned_bundle(self._client, pointer, staged_bundle)
            if destination.exists() or destination.is_symlink():
                raise FileExistsError("bundle destination appeared during atomic hydration")
            os.rename(staged_bundle, destination)
            published = True
            _fsync_directory(parent)
            installed_metadata = inspect_bundle(destination)
            verify_target_identity(installed_metadata, pointer.target_identity)
            return InstalledBundle(
                path=destination,
                metadata=installed_metadata,
                reused_existing=False,
            )
        except BaseException:
            if published:
                with suppress(OSError):
                    if destination.is_symlink():
                        destination.unlink()
                    elif destination.exists():
                        shutil.rmtree(destination)
                with suppress(OSError):
                    _fsync_directory(parent)
            raise
        finally:
            if staging_root.exists():
                shutil.rmtree(staging_root)
