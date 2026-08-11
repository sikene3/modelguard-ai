"""Fail-closed reusable checks for the Publication Audit."""

from __future__ import annotations

import hashlib
import re

# security-suppression:
# finding=B404
# justification=Only a caller-supplied Git argument array runs without a shell.
# owner=modelguard-maintainers
# expires=2026-10-31
import subprocess  # nosec B404
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

PARTIAL_CLONE_PROMISOR_PATTERN = r"^(extensions\.partialclone|remote\..*\.promisor)$"
PUBLICATION_EMAIL_PATTERN = re.compile(
    rb"(?i)(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![A-Z0-9._%+-])"
)
PUBLICATION_EXAMPLE_DOMAINS = frozenset(
    {b"example.com", b"example.net", b"example.org", b"example.invalid"}
)
PUBLICATION_RESERVED_TEST_SUFFIXES = (b".invalid", b".test")
PUBLICATION_EXACT_SYNTHETIC_TEST_EMAIL_SHA256S = frozenset(
    {"6dcda26c226c13dfcddc8ea184dd7123e401dda2fee64b611e9c3fc205132b1e"}
)
PUBLICATION_PRIVATE_KEY_BEGIN_BOUNDARY = re.compile(
    rb"(?i)(?<!-)-{4,}[ \t]*BEGIN[ \t]+"
    rb"(?:[A-Z0-9][A-Z0-9_-]{0,31}[ \t]+){0,4}"
    rb"PRIVATE[ \t]+KEY"
    rb"(?:[ \t]+[A-Z0-9][A-Z0-9_-]{0,31}){0,2}"
    rb"[ \t]*-{4,}(?!-)"
)

PublicationEmailClassification = Literal[
    "verified_github_noreply",
    "synthetic_example_domain",
    "synthetic_exact_test_identity",
    "synthetic_reserved_test_domain",
]


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


def _is_tests_only_blob(paths: Sequence[str]) -> bool:
    if not paths:
        return False
    for value in paths:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "tests":
            return False
    return True


def classify_publication_email_match(
    value: bytes,
    *,
    expected_noreply: bytes,
    blob_paths: Sequence[str],
) -> PublicationEmailClassification:
    """Classify one matched value without exposing it in errors or evidence."""

    if PUBLICATION_EMAIL_PATTERN.fullmatch(value) is None:
        raise PublicationAuditGitError("publication_email_match_invalid")
    if PUBLICATION_EMAIL_PATTERN.fullmatch(
        expected_noreply
    ) is None or not expected_noreply.lower().endswith(b"@users.noreply.github.com"):
        raise PublicationAuditGitError("verified_github_noreply_invalid")

    normalized = value.lower()
    if normalized == expected_noreply.lower():
        return "verified_github_noreply"
    if (
        _is_tests_only_blob(blob_paths)
        and hashlib.sha256(normalized).hexdigest() in PUBLICATION_EXACT_SYNTHETIC_TEST_EMAIL_SHA256S
    ):
        return "synthetic_exact_test_identity"
    domain = normalized.rsplit(b"@", 1)[1]
    if domain in PUBLICATION_EXAMPLE_DOMAINS:
        return "synthetic_example_domain"
    if domain.endswith(PUBLICATION_RESERVED_TEST_SUFFIXES) and _is_tests_only_blob(blob_paths):
        return "synthetic_reserved_test_domain"
    raise PublicationAuditRefusal("privacy_history_blob_email_present")


def require_safe_publication_email_matches(
    data: bytes,
    *,
    expected_noreply: bytes,
    blob_paths: Sequence[str],
) -> tuple[PublicationEmailClassification, ...]:
    """Validate every email-shaped value while returning only safe classifications."""

    return tuple(
        classify_publication_email_match(
            match.group(1),
            expected_noreply=expected_noreply,
            blob_paths=blob_paths,
        )
        for match in PUBLICATION_EMAIL_PATTERN.finditer(data)
    )


def contains_publication_private_key_material(data: bytes) -> bool:
    """Identify a literal private-key envelope without matching detector expressions.

    A begin boundary is sufficient: incomplete envelopes and invalid payloads must remain
    fail-closed. Regex metacharacters in a scanner's own detector label do not form a literal
    cryptographic boundary and therefore do not match.
    """

    return PUBLICATION_PRIVATE_KEY_BEGIN_BOUNDARY.search(data) is not None


def require_no_publication_private_key_material(data: bytes) -> None:
    """Refuse literal PEM/OpenSSH private-key material without disclosing its bytes."""

    if contains_publication_private_key_material(data):
        raise PublicationAuditRefusal("privacy_history_blob_private_key_present")


def _run_git_config(command: Sequence[str], repository: Path) -> subprocess.CompletedProcess[str]:
    # security-suppression:
    # finding=B603
    # justification=The command is an argument sequence and shell execution is never enabled.
    # owner=modelguard-maintainers
    # expires=2026-10-31
    return subprocess.run(  # nosec B603
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
