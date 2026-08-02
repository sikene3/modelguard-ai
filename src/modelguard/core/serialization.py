"""Strict JSON serialization helpers for auditable artifacts."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


class StrictArtifactModel(BaseModel):
    """Base model used by versioned JSON contracts."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def utc_now_iso() -> str:
    """Return a second-precision UTC timestamp in ISO 8601 form."""

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _json_ready(value.model_dump(mode="json", by_alias=True))
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON artifacts cannot contain NaN or Infinity")
    if isinstance(value, Path):
        return value.as_posix()
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON deterministically with sorted keys and no non-finite numbers."""

    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    """Write a human-readable strict JSON artifact with a trailing newline."""

    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    path.write_text(f"{serialized}\n", encoding="utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def parse_strict_json_bytes(payload: bytes) -> Any:
    """Parse UTF-8 JSON while rejecting duplicate keys and non-finite extensions."""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("JSON artifact must be valid UTF-8") from error
    return json.loads(
        text,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_non_finite_constant,
    )


def load_strict_json(path: Path) -> Any:
    """Parse JSON while rejecting duplicate keys and NaN/Infinity extensions."""

    return parse_strict_json_bytes(path.read_bytes())


def load_json_model[ArtifactModelT: StrictArtifactModel](
    path: Path, model_type: type[ArtifactModelT]
) -> ArtifactModelT:
    """Parse a strict JSON file into an extra-forbid Pydantic contract."""

    return model_type.model_validate(load_strict_json(path))
