"""Read-only local and S3 repositories for dashboard evidence artifacts."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from errno import ELOOP
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from modelguard.dashboard.config import DashboardRepositoryMode, DashboardSettings

REPORT_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
WINDOW_KEY_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")


class DashboardRepositoryError(RuntimeError):
    """A bounded repository error safe to reduce to a user-facing category."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


@dataclass(frozen=True)
class RawArtifact:
    payload: bytes
    modified_at: datetime | None


@dataclass(frozen=True)
class HtmlReportAccess:
    filename: str
    content: bytes | None = None
    url: str | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if (self.content is None) == (self.url is None):
            raise ValueError("HTML access must contain exactly one of content or URL")


class DashboardRepository(Protocol):
    """The same evidence-reading surface for local files and S3 objects."""

    @property
    def mode(self) -> DashboardRepositoryMode: ...

    def read_latest_report(self) -> RawArtifact | None: ...

    def read_run_status(self) -> RawArtifact | None: ...

    def read_active_model_manifest(self) -> RawArtifact | None: ...

    def list_recent_reports(self, *, limit: int) -> tuple[RawArtifact, ...]: ...

    def html_report_access(
        self,
        *,
        report_id: str,
        window_end: datetime,
        now: datetime,
    ) -> HtmlReportAccess | None: ...


def _window_key(value: datetime) -> str:
    if value.utcoffset() != timedelta(0):
        raise ValueError("report window end must be UTC")
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _validate_report_id(report_id: str) -> None:
    if REPORT_ID_PATTERN.fullmatch(report_id) is None:
        raise ValueError("report ID must be a SHA-256 digest")


class LocalDashboardRepository:
    """Safely read monitor outputs and the configured active local manifest."""

    mode = DashboardRepositoryMode.LOCAL

    def __init__(
        self,
        *,
        report_root: Path,
        model_bundle_path: Path,
        max_json_bytes: int,
        max_html_bytes: int,
    ) -> None:
        self._report_root = report_root
        self._model_bundle_path = model_bundle_path
        self._max_json_bytes = max_json_bytes
        self._max_html_bytes = max_html_bytes

    @staticmethod
    def _read_regular(path: Path, *, maximum_bytes: int) -> RawArtifact | None:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None
        except OSError as error:
            category = (
                "unsafe_local_artifact" if error.errno == ELOOP else "local_artifact_unavailable"
            )
            raise DashboardRepositoryError(category) from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise DashboardRepositoryError("unsafe_local_artifact")
            if metadata.st_size > maximum_bytes:
                raise DashboardRepositoryError("artifact_size_limit_exceeded")
            chunks: list[bytes] = []
            remaining = maximum_bytes + 1
            while remaining:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if len(payload) > maximum_bytes:
                raise DashboardRepositoryError("artifact_size_limit_exceeded")
            modified_at = datetime.fromtimestamp(metadata.st_mtime, tz=UTC)
            return RawArtifact(payload=payload, modified_at=modified_at)
        except OSError as error:
            raise DashboardRepositoryError("local_artifact_unavailable") from error
        finally:
            os.close(descriptor)

    @staticmethod
    def _require_safe_directory(path: Path) -> bool:
        if not path.exists():
            return False
        if path.is_symlink() or not path.is_dir():
            raise DashboardRepositoryError("unsafe_local_artifact")
        return True

    def read_latest_report(self) -> RawArtifact | None:
        if not self._require_safe_directory(self._report_root):
            return None
        return self._read_regular(
            self._report_root / "latest.json",
            maximum_bytes=self._max_json_bytes,
        )

    def read_run_status(self) -> RawArtifact | None:
        if not self._require_safe_directory(self._report_root):
            return None
        return self._read_regular(
            self._report_root / "run-status.json",
            maximum_bytes=self._max_json_bytes,
        )

    def read_active_model_manifest(self) -> RawArtifact | None:
        if not self._require_safe_directory(self._model_bundle_path):
            return None
        return self._read_regular(
            self._model_bundle_path / "manifest.json",
            maximum_bytes=self._max_json_bytes,
        )

    def list_recent_reports(self, *, limit: int) -> tuple[RawArtifact, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("history limit must be in [1, 100]")
        history_root = self._report_root / "history"
        if not self._require_safe_directory(history_root):
            return ()
        candidates: list[Path] = []
        try:
            for window_directory in history_root.iterdir():
                if WINDOW_KEY_PATTERN.fullmatch(window_directory.name) is None:
                    continue
                if window_directory.is_symlink() or not window_directory.is_dir():
                    raise DashboardRepositoryError("unsafe_local_artifact")
                for artifact_path in window_directory.glob("*.json"):
                    if artifact_path.is_symlink():
                        raise DashboardRepositoryError("unsafe_local_artifact")
                    if REPORT_ID_PATTERN.fullmatch(artifact_path.stem) is not None:
                        candidates.append(artifact_path)
                        if len(candidates) > 5_000:
                            raise DashboardRepositoryError("history_listing_limit_exceeded")
        except OSError as error:
            raise DashboardRepositoryError("local_artifact_unavailable") from error
        selected = sorted(candidates, key=lambda path: (path.parent.name, path.name), reverse=True)[
            :limit
        ]
        artifacts: list[RawArtifact] = []
        for path in selected:
            artifact = self._read_regular(path, maximum_bytes=self._max_json_bytes)
            if artifact is not None:
                artifacts.append(artifact)
        return tuple(artifacts)

    def html_report_access(
        self,
        *,
        report_id: str,
        window_end: datetime,
        now: datetime,
    ) -> HtmlReportAccess | None:
        del now
        _validate_report_id(report_id)
        window_key = _window_key(window_end)
        history_root = self._report_root / "history"
        window_root = history_root / window_key
        if not self._require_safe_directory(history_root) or not self._require_safe_directory(
            window_root
        ):
            return None
        artifact = self._read_regular(
            window_root / f"{report_id}.html",
            maximum_bytes=self._max_html_bytes,
        )
        if artifact is None:
            return None
        return HtmlReportAccess(
            filename=f"modelguard-report-{window_key}-{report_id[:12]}.html",
            content=artifact.payload,
        )


class ReadableBody(Protocol):
    def read(self, amount: int = -1) -> bytes: ...

    def close(self) -> None: ...


class DashboardS3Client(Protocol):
    def get_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def head_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def list_objects_v2(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str: ...


def _client_error_code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))


def _is_missing(error: ClientError) -> bool:
    return _client_error_code(error) in {"NoSuchKey", "404", "NotFound"}


class S3DashboardRepository:
    """Read the same evidence contract from private S3 and issue only short HTTPS links."""

    mode = DashboardRepositoryMode.S3

    def __init__(
        self,
        client: DashboardS3Client,
        *,
        report_bucket: str,
        model_bucket: str,
        active_model_version: str,
        report_prefix: str,
        model_prefix: str,
        max_json_bytes: int,
        presigned_url_ttl_seconds: int,
    ) -> None:
        if not report_bucket or not model_bucket:
            raise ValueError("S3 dashboard buckets cannot be empty")
        self._client = client
        self._report_bucket = report_bucket
        self._model_bucket = model_bucket
        self._active_model_version = active_model_version
        self._report_prefix = report_prefix
        self._model_prefix = model_prefix
        self._max_json_bytes = max_json_bytes
        self._presigned_url_ttl_seconds = presigned_url_ttl_seconds

    def _read_object(self, *, bucket: str, key: str) -> RawArtifact | None:
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
        except ClientError as error:
            if _is_missing(error):
                return None
            raise DashboardRepositoryError("s3_artifact_unavailable") from error
        except (BotoCoreError, TimeoutError) as error:
            raise DashboardRepositoryError("s3_artifact_unavailable") from error
        length = response.get("ContentLength")
        if isinstance(length, int) and length > self._max_json_bytes:
            raise DashboardRepositoryError("artifact_size_limit_exceeded")
        body = response.get("Body")
        if body is None or not hasattr(body, "read"):
            raise DashboardRepositoryError("invalid_s3_object_response")
        body_reader = cast(ReadableBody, body)
        try:
            payload = body_reader.read(self._max_json_bytes + 1)
        except (BotoCoreError, OSError, TimeoutError) as error:
            raise DashboardRepositoryError("s3_artifact_unavailable") from error
        finally:
            try:
                body_reader.close()
            except (BotoCoreError, OSError) as error:
                raise DashboardRepositoryError("s3_artifact_unavailable") from error
        if not isinstance(payload, bytes):
            raise DashboardRepositoryError("invalid_s3_object_response")
        if len(payload) > self._max_json_bytes:
            raise DashboardRepositoryError("artifact_size_limit_exceeded")
        modified = response.get("LastModified")
        modified_at = (
            modified.astimezone(UTC)
            if isinstance(modified, datetime) and modified.tzinfo is not None
            else None
        )
        return RawArtifact(payload=payload, modified_at=modified_at)

    def read_latest_report(self) -> RawArtifact | None:
        return self._read_object(
            bucket=self._report_bucket,
            key=f"{self._report_prefix}latest.json",
        )

    def read_run_status(self) -> RawArtifact | None:
        return self._read_object(
            bucket=self._report_bucket,
            key=f"{self._report_prefix}run-status.json",
        )

    def read_active_model_manifest(self) -> RawArtifact | None:
        return self._read_object(
            bucket=self._model_bucket,
            key=(f"{self._model_prefix}{self._active_model_version}/manifest.json"),
        )

    def list_recent_reports(self, *, limit: int) -> tuple[RawArtifact, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("history limit must be in [1, 100]")
        keys: list[str] = []
        token: str | None = None
        history_prefix = f"{self._report_prefix}history/"
        key_pattern = re.compile(
            rf"^{re.escape(history_prefix)}[0-9]{{8}}T[0-9]{{6}}Z/[0-9a-f]{{64}}\.json$"
        )
        for _ in range(100):
            request: dict[str, Any] = {
                "Bucket": self._report_bucket,
                "Prefix": history_prefix,
            }
            if token is not None:
                request["ContinuationToken"] = token
            try:
                response = self._client.list_objects_v2(**request)
            except (BotoCoreError, ClientError, TimeoutError) as error:
                raise DashboardRepositoryError("s3_history_unavailable") from error
            contents = response.get("Contents", [])
            if not isinstance(contents, list):
                raise DashboardRepositoryError("invalid_s3_listing_response")
            for item in contents:
                if not isinstance(item, Mapping) or not isinstance(item.get("Key"), str):
                    raise DashboardRepositoryError("invalid_s3_listing_response")
                key = str(item["Key"])
                if key_pattern.fullmatch(key) is not None:
                    keys.append(key)
                    if len(keys) > 5_000:
                        raise DashboardRepositoryError("history_listing_limit_exceeded")
            if not response.get("IsTruncated", False):
                break
            next_token = response.get("NextContinuationToken")
            if not isinstance(next_token, str) or not next_token or next_token == token:
                raise DashboardRepositoryError("invalid_s3_listing_response")
            token = next_token
        else:
            raise DashboardRepositoryError("history_listing_limit_exceeded")
        selected = sorted(set(keys), reverse=True)[:limit]
        artifacts: list[RawArtifact] = []
        for key in selected:
            artifact = self._read_object(bucket=self._report_bucket, key=key)
            if artifact is not None:
                artifacts.append(artifact)
        return tuple(artifacts)

    def html_report_access(
        self,
        *,
        report_id: str,
        window_end: datetime,
        now: datetime,
    ) -> HtmlReportAccess | None:
        _validate_report_id(report_id)
        if now.utcoffset() != timedelta(0):
            raise ValueError("HTML access timestamp must be UTC")
        window_key = _window_key(window_end)
        key = f"{self._report_prefix}history/{window_key}/{report_id}.html"
        try:
            self._client.head_object(Bucket=self._report_bucket, Key=key)
        except ClientError as error:
            if _is_missing(error):
                return None
            raise DashboardRepositoryError("s3_html_report_unavailable") from error
        except (BotoCoreError, TimeoutError) as error:
            raise DashboardRepositoryError("s3_html_report_unavailable") from error
        filename = f"modelguard-report-{window_key}-{report_id[:12]}.html"
        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self._report_bucket,
                    "Key": key,
                    "ResponseContentDisposition": f'attachment; filename="{filename}"',
                    "ResponseContentType": "text/html; charset=utf-8",
                },
                ExpiresIn=self._presigned_url_ttl_seconds,
                HttpMethod="GET",
            )
        except (BotoCoreError, ClientError, ValueError) as error:
            raise DashboardRepositoryError("s3_html_report_unavailable") from error
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise DashboardRepositoryError("unsafe_presigned_report_url")
        return HtmlReportAccess(
            filename=filename,
            url=url,
            expires_at=now.astimezone(UTC) + timedelta(seconds=self._presigned_url_ttl_seconds),
        )


def build_dashboard_repository(
    settings: DashboardSettings,
    *,
    s3_client: DashboardS3Client | None = None,
) -> DashboardRepository:
    """Build one repository; the optional client keeps every AWS test network-free."""

    if settings.dashboard_repository is DashboardRepositoryMode.LOCAL:
        return LocalDashboardRepository(
            report_root=settings.local_report_dir,
            model_bundle_path=settings.model_bundle_path,
            max_json_bytes=settings.dashboard_max_json_bytes,
            max_html_bytes=settings.dashboard_max_html_bytes,
        )
    client = s3_client
    if client is None:
        boto_config = Config(
            connect_timeout=settings.dashboard_aws_connect_timeout_seconds,
            read_timeout=settings.dashboard_aws_read_timeout_seconds,
            retries={"max_attempts": 2, "mode": "standard"},
        )
        try:
            client = cast(
                DashboardS3Client,
                boto3.client(
                    "s3",
                    region_name=settings.aws_region,
                    endpoint_url=settings.dashboard_s3_endpoint_url,
                    config=boto_config,
                ),
            )
        except (BotoCoreError, ValueError) as error:
            raise DashboardRepositoryError("s3_client_unavailable") from error
    if settings.report_bucket is None or settings.model_bucket is None:
        raise ValueError("S3 dashboard settings were not validated")
    return S3DashboardRepository(
        client,
        report_bucket=settings.report_bucket,
        model_bucket=settings.model_bucket,
        active_model_version=settings.active_model_version,
        report_prefix=settings.dashboard_report_prefix,
        model_prefix=settings.dashboard_model_prefix,
        max_json_bytes=settings.dashboard_max_json_bytes,
        presigned_url_ttl_seconds=settings.dashboard_presigned_url_ttl_seconds,
    )
