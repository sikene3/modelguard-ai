#!/usr/bin/env python3
"""Validate that every scanner suppression is exact, owned, justified, and expiring."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.secret_scan_policy import load_allowlist

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
MAX_LIFETIME = timedelta(days=90)
CHECKOV_PATTERN = re.compile(
    r"checkov:skip=(?P<finding>CKV[A-Za-z0-9_]+):(?P<justification>.+) "
    r"\[owner=(?P<owner>[A-Za-z0-9_.@/-]+); expires=(?P<expires>[0-9]{4}-[0-9]{2}-[0-9]{2})\]$"
)
SHELLCHECK_PATTERN = re.compile(r"#\s*shellcheck\s+disable=(?P<finding>SC[0-9]+)$")


class SecurityPolicyError(RuntimeError):
    """A scanner-suppression policy violation."""


def _safe_exact_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and not any(token in value for token in "*?[]")
    )


def _validate_expiry(value: str, *, as_of: date, context: str) -> None:
    is_end_of_day = re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T23:59:59Z", value)
    normalized = value[:10] if is_end_of_day else value
    try:
        expiry = date.fromisoformat(normalized)
    except ValueError as error:
        raise SecurityPolicyError(f"{context} has an invalid expiry") from error
    if expiry < as_of:
        raise SecurityPolicyError(f"{context} is expired")
    if expiry > as_of + MAX_LIFETIME:
        raise SecurityPolicyError(f"{context} expiry exceeds 90 days")


def validate_checkov(root: Path, *, as_of: date) -> int:
    """Validate every inline Checkov skip as one complete suppression record."""

    count = 0
    candidates = [
        path
        for path in _approved_text_files(root)
        if path.suffix in {".tf", ".yml", ".yaml"} or path.name.endswith("Dockerfile")
    ]
    for path in candidates:
        relative = path.relative_to(root).as_posix()
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "checkov:skip=" not in line:
                continue
            match = CHECKOV_PATTERN.search(line.strip())
            if match is None:
                raise SecurityPolicyError(
                    f"Checkov suppression metadata is incomplete at {relative}:{line_number}"
                )
            if len(match["justification"].strip()) < 20:
                raise SecurityPolicyError(
                    f"Checkov suppression justification is too short at {relative}:{line_number}"
                )
            _validate_expiry(
                match["expires"],
                as_of=as_of,
                context=f"Checkov suppression {relative}:{line_number}",
            )
            count += 1
    if count == 0:
        raise SecurityPolicyError("no reviewed Checkov suppressions were found")
    return count


def _approved_text_files(root: Path) -> list[Path]:
    # security-suppression:
    # finding=B404
    # justification=Only the fixed local Git enumeration runs without a shell.
    # owner=modelguard-maintainers
    # expires=2026-10-31
    import subprocess  # nosec B404

    # security-suppression:
    # finding=B603,B607
    # justification=The executable and arguments are fixed; no shell input is accepted.
    # owner=modelguard-maintainers
    # expires=2026-10-31
    result = subprocess.run(  # nosec B603, B607
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    paths: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            relative = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        path = root / relative
        if path.is_file():
            paths.append(path)
    return paths


def validate_shellcheck(root: Path, *, as_of: date) -> int:
    """Require an adjacent complete record for every ShellCheck disable directive."""

    count = 0
    for path in _approved_text_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        relative = path.relative_to(root).as_posix()
        for index, line in enumerate(lines):
            directive = SHELLCHECK_PATTERN.search(line.strip())
            if directive is None:
                continue
            if index < 5:
                raise SecurityPolicyError(
                    f"ShellCheck suppression metadata is missing at {relative}:{index + 1}"
                )
            block = [item.strip() for item in lines[index - 5 : index]]
            if block[0] != "# security-suppression:":
                raise SecurityPolicyError(
                    f"ShellCheck suppression metadata is incomplete at {relative}:{index + 1}"
                )
            try:
                policy = {
                    item.removeprefix("# ").split("=", 1)[0]: item.removeprefix("# ").split("=", 1)[
                        1
                    ]
                    for item in block[1:]
                }
            except (IndexError, ValueError) as error:
                raise SecurityPolicyError(
                    f"ShellCheck suppression metadata is malformed at {relative}:{index + 1}"
                ) from error
            if (
                set(policy) != {"finding", "justification", "owner", "expires"}
                or policy["finding"] != directive["finding"]
                or len(policy["justification"].strip()) < 20
                or re.fullmatch(r"[A-Za-z0-9_.@/-]+", policy["owner"]) is None
            ):
                raise SecurityPolicyError(
                    f"ShellCheck suppression metadata is incomplete at {relative}:{index + 1}"
                )
            _validate_expiry(
                policy["expires"],
                as_of=as_of,
                context=f"ShellCheck suppression {relative}:{index + 1}",
            )
            count += 1
    return count


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_trivy(root: Path, *, as_of: date) -> int:
    """Validate the only approved Trivy exception registry and forbid hidden ignore files."""

    forbidden = [root / ".trivyignore", root / ".trivyignore.yaml", root / ".trivyignore.yml"]
    if any(path.exists() for path in forbidden):
        raise SecurityPolicyError("unreviewed Trivy ignore file is forbidden")
    for path in _approved_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if re.search(r"(?i)trivy\s*:\s*ignore", text):
            raise SecurityPolicyError(
                f"inline Trivy suppression is forbidden in {path.relative_to(root).as_posix()}"
            )

    repository_path = root / "security" / "trivy-ignore.yaml"
    repository_policy = _read_json(repository_path)
    if not isinstance(repository_policy, dict) or set(repository_policy) != {"misconfigurations"}:
        raise SecurityPolicyError("repository Trivy ignore policy is malformed")
    repository_entries = repository_policy["misconfigurations"]
    if not isinstance(repository_entries, list):
        raise SecurityPolicyError("repository Trivy misconfigurations must be a list")
    seen_repository_entries: set[tuple[str, str]] = set()
    for index, raw in enumerate(repository_entries):
        if not isinstance(raw, dict) or set(raw) != {
            "id",
            "paths",
            "statement",
            "expired_at",
        }:
            raise SecurityPolicyError(f"repository Trivy suppression {index} has invalid fields")
        finding = raw["id"]
        paths = raw["paths"]
        statement = raw["statement"]
        if (
            not isinstance(finding, str)
            or re.fullmatch(r"[A-Z]+-[0-9]{4}", finding) is None
            or not isinstance(paths, list)
            or len(paths) != 1
            or not isinstance(paths[0], str)
            or not _safe_exact_path(paths[0])
            or not isinstance(statement, str)
            or re.fullmatch(r"owner=[A-Za-z0-9_.@/-]+; justification=.{20,}", statement) is None
        ):
            raise SecurityPolicyError(
                f"repository Trivy suppression {index} is not exact, justified, and owned"
            )
        key = (finding, paths[0])
        if key in seen_repository_entries:
            raise SecurityPolicyError("repository Trivy suppression is duplicated")
        seen_repository_entries.add(key)
        _validate_expiry(
            str(raw["expired_at"]),
            as_of=as_of,
            context=f"repository Trivy suppression {index}",
        )

    path = root / "configs" / "trivy-exceptions.json"
    payload = _read_json(path)
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "exceptions"}:
        raise SecurityPolicyError("Trivy exception registry is malformed")
    if payload["schema_version"] != "modelguard.trivy-exceptions.v1":
        raise SecurityPolicyError("Trivy exception registry schema is unsupported")
    entries = payload["exceptions"]
    if not isinstance(entries, list):
        raise SecurityPolicyError("Trivy exceptions must be a list")
    required = {
        "image",
        "vulnerability_id",
        "package_name",
        "rationale",
        "owner",
        "expires_on",
    }
    for index, raw in enumerate(entries):
        if not isinstance(raw, dict) or set(raw) != required:
            raise SecurityPolicyError(f"Trivy exception {index} has invalid fields")
        if (
            not isinstance(raw["vulnerability_id"], str)
            or not raw["vulnerability_id"]
            or not isinstance(raw["rationale"], str)
            or len(raw["rationale"].strip()) < 20
            or not isinstance(raw["owner"], str)
            or not raw["owner"].strip()
        ):
            raise SecurityPolicyError(f"Trivy exception {index} is not exact and owned")
        _validate_expiry(str(raw["expires_on"]), as_of=as_of, context=f"Trivy exception {index}")
    return len(entries) + len(repository_entries)


def validate(root: Path = REPOSITORY_ROOT, *, as_of: date | None = None) -> dict[str, int]:
    """Validate all version-controlled scanner suppression boundaries."""

    evaluation_date = as_of or datetime.now(UTC).date()
    checkov = validate_checkov(root, as_of=evaluation_date)
    shellcheck = validate_shellcheck(root, as_of=evaluation_date)
    trivy = validate_trivy(root, as_of=evaluation_date)
    gitleaks = load_allowlist(
        root / ".github" / "secret-scanning-allowlist.json", today=evaluation_date
    )
    return {
        "checkov": checkov,
        "shellcheck": shellcheck,
        "trivy": trivy,
        "gitleaks": len(gitleaks.entries),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--as-of", type=date.fromisoformat)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        counts = validate(args.repository_root.resolve(), as_of=args.as_of)
    except (OSError, UnicodeError, json.JSONDecodeError, SecurityPolicyError, ValueError) as error:
        print(json.dumps({"status": "refused", "reason": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps({"status": "passed", "suppressions": counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
