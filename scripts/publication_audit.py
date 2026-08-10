"""Fail-closed Git configuration checks for the Publication Audit."""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

PARTIAL_CLONE_PROMISOR_PATTERN = r"^(extensions\.partialclone|remote\..*\.promisor)$"


class PublicationAuditGitError(RuntimeError):
    """Raised when Git cannot complete a Publication Audit query."""


class PublicationAuditRefusal(ValueError):
    """Raised when repository configuration violates the publication contract."""


@dataclass(frozen=True)
class GitConfigMatch:
    """One validated key/value returned by ``git config --get-regexp``."""

    key: str
    value: str


GitConfigRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


def _run_git_config(command: Sequence[str], repository: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )


def query_partial_clone_promisor_config(
    repository: Path,
    *,
    runner: GitConfigRunner = _run_git_config,
) -> tuple[GitConfigMatch, ...]:
    """Return matching Git configuration, accepting exit 1 only as no matches."""

    command = (
        "git",
        "config",
        "--get-regexp",
        PARTIAL_CLONE_PROMISOR_PATTERN,
    )
    result = runner(command, repository)
    if result.stderr:
        sys.stderr.write(result.stderr)
        sys.stderr.flush()

    if result.returncode == 1:
        if result.stdout:
            raise PublicationAuditGitError("git_config_empty_result_has_output")
        return ()
    if result.returncode != 0:
        raise PublicationAuditGitError(f"git_config_query_failed_exit_{result.returncode}")
    if not result.stdout:
        raise PublicationAuditGitError("git_config_match_result_is_empty")

    matches: list[GitConfigMatch] = []
    pattern = re.compile(PARTIAL_CLONE_PROMISOR_PATTERN, flags=re.IGNORECASE)
    for line in result.stdout.splitlines():
        key, separator, value = line.partition(" ")
        if not separator or not value or pattern.fullmatch(key) is None:
            raise PublicationAuditGitError("git_config_match_result_is_invalid")
        matches.append(GitConfigMatch(key=key, value=value))
    return tuple(matches)


def require_no_partial_clone_or_promisor_config(
    repository: Path,
    *,
    runner: GitConfigRunner = _run_git_config,
) -> None:
    """Refuse any matching partial-clone or promisor configuration."""

    matches = query_partial_clone_promisor_config(repository, runner=runner)
    if matches:
        raise PublicationAuditRefusal("partial_clone_or_promisor_config_present")
