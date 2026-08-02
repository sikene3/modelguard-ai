"""Small structured-logging boundary with centralized redaction."""

from __future__ import annotations

import json
import logging
import math
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Protocol, TextIO

from pydantic import SecretStr

from modelguard.core.config import LogLevel

REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "body",
    "credential",
    "environment",
    "feature",
    "password",
    "secret",
    "token",
)


class StructuredLogger(Protocol):
    """Dependency-injected application logger used at trust boundaries."""

    def info(self, event: str, **fields: object) -> None:
        """Write one informational JSON event."""

    def warning(self, event: str, **fields: object) -> None:
        """Write one warning JSON event."""

    def error(self, event: str, **fields: object) -> None:
        """Write one error JSON event without implicitly exposing exception text."""


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _redact_text(value: str, sensitive_values: tuple[str, ...]) -> str:
    sanitized = value
    for sensitive in sensitive_values:
        if sensitive:
            sanitized = sanitized.replace(sensitive, REDACTED)
    return sanitized


def _redact_value(value: object, sensitive_values: tuple[str, ...]) -> object:
    if isinstance(value, SecretStr):
        return REDACTED
    if isinstance(value, Enum):
        return _redact_value(value.value, sensitive_values)
    if isinstance(value, Path):
        return _redact_text(value.as_posix(), sensitive_values)
    if isinstance(value, float):
        return value if math.isfinite(value) else "non_finite"
    if isinstance(value, str):
        return _redact_text(value, sensitive_values)
    if isinstance(value, Mapping):
        return {
            _redact_text(str(key), sensitive_values): (
                REDACTED
                if any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
                else _redact_value(item, sensitive_values)
            )
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_redact_value(item, sensitive_values) for item in value]
    if value is None or isinstance(value, (bool, int)):
        return value
    return _redact_text(str(value), sensitive_values)


class JsonLogger:
    """Serialize one complete application event per stdout line."""

    def __init__(
        self,
        logger: logging.Logger,
        *,
        sensitive_values: tuple[str, ...] = (),
    ) -> None:
        self._logger = logger
        self._sensitive_values = sensitive_values

    def _write(self, level: int, event: str, fields: dict[str, object]) -> None:
        payload: dict[str, object] = {
            "timestamp": _utc_timestamp(),
            "level": logging.getLevelName(level).lower(),
            "event": event,
        }
        for key, value in fields.items():
            payload[key] = (
                REDACTED
                if any(part in key.lower() for part in _SENSITIVE_KEY_PARTS)
                else _redact_value(value, self._sensitive_values)
            )
        self._logger.log(
            level,
            json.dumps(payload, allow_nan=False, ensure_ascii=False, separators=(",", ":")),
        )

    def info(self, event: str, **fields: object) -> None:
        self._write(logging.INFO, event, fields)

    def warning(self, event: str, **fields: object) -> None:
        self._write(logging.WARNING, event, fields)

    def error(self, event: str, **fields: object) -> None:
        self._write(logging.ERROR, event, fields)


def configure_json_logging(
    level: LogLevel,
    *,
    stream: TextIO | None = None,
    sensitive_values: tuple[str, ...] = (),
) -> JsonLogger:
    """Configure the dedicated application logger without altering the root logger."""

    logger = logging.getLogger("modelguard.api")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(level.value)
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return JsonLogger(logger, sensitive_values=sensitive_values)
