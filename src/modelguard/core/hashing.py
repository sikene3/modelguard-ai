"""Canonical SHA-256 lineage records."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from modelguard.core.serialization import StrictArtifactModel, canonical_json_bytes


class HashRecord(StrictArtifactModel):
    """A digest plus the rules needed to reproduce its identity."""

    algorithm: Literal["sha256"] = "sha256"
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonicalization_version: str
    ordering: str
    exclusions: list[str]


def sha256_bytes(payload: bytes) -> str:
    """Return a lowercase SHA-256 digest for bytes."""

    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a regular file without following repository-wide state."""

    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_hash(
    value: Any,
    *,
    ordering: str,
    exclusions: Sequence[str],
    canonicalization_version: str = "modelguard.canonical-json.v1",
) -> HashRecord:
    """Hash a JSON value using the declared canonical identity rules."""

    return HashRecord(
        digest=sha256_bytes(canonical_json_bytes(value)),
        canonicalization_version=canonicalization_version,
        ordering=ordering,
        exclusions=list(exclusions),
    )


def raw_file_hash(path: Path, *, exclusions: Sequence[str] = ()) -> HashRecord:
    """Describe the SHA-256 identity of a file's exact bytes."""

    return HashRecord(
        digest=sha256_file(path),
        canonicalization_version="modelguard.raw-bytes.v1",
        ordering="raw byte sequence",
        exclusions=list(exclusions),
    )


def source_tree_hash(
    repository_root: Path,
    paths: Iterable[Path],
    *,
    exclusions: Sequence[str],
) -> HashRecord:
    """Hash sorted relative paths, sizes, and byte digests for a source tree."""

    entries: list[dict[str, str | int]] = []
    resolved_root = repository_root.resolve()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        relative_path = path.resolve().relative_to(resolved_root).as_posix()
        entries.append(
            {
                "path": relative_path,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return canonical_json_hash(
        entries,
        canonicalization_version="modelguard.path-digest-tree.v1",
        ordering="repository-relative POSIX path ascending",
        exclusions=exclusions,
    )
