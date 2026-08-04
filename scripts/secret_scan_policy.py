#!/usr/bin/env python3
"""Validate scoped secret-scan exceptions and emit value-free Gitleaks evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class SecretScanPolicyError(RuntimeError):
    """A safe refusal reason that never contains a matched value."""


MAX_ALLOWLIST_LIFETIME = timedelta(days=90)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AllowlistEntry(StrictModel):
    fingerprint: str = Field(min_length=10, max_length=500)
    path: str = Field(min_length=1, max_length=300)
    rule_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    rationale: str = Field(min_length=20, max_length=500)
    owner: str = Field(pattern=r"^[A-Za-z0-9_.@/-]{2,100}$")
    expires_at: date

    @field_validator("rationale")
    @classmethod
    def substantive_rationale(cls, value: str) -> str:
        if value != value.strip() or len(value.strip()) < 20:
            raise ValueError("allowlist rationale must be substantive and trimmed")
        return value

    @field_validator("path")
    @classmethod
    def exact_repository_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or ".." in path.parts
            or any(token in value for token in "*?[]")
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("allowlist path must be one exact repository-relative path")
        return value

    @model_validator(mode="after")
    def fingerprint_matches_exact_scope(self) -> AllowlistEntry:
        prefix = f"{self.commit}:{self.path}:{self.rule_id}:"
        if re.fullmatch(re.escape(prefix) + r"[1-9][0-9]*", self.fingerprint) is None:
            raise ValueError("allowlist fingerprint must match commit:path:rule_id:start_line")
        return self


class SecretScanAllowlist(StrictModel):
    schema_version: Literal["modelguard.secret-scan-allowlist.v1"]
    entries: tuple[AllowlistEntry, ...]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_allowlist(path: Path, *, today: date | None = None) -> SecretScanAllowlist:
    """Load an exact, non-expired allowlist and reject duplicate scopes."""

    policy = SecretScanAllowlist.model_validate(_load_json(path))
    evaluation_date = today or datetime.now(tz=UTC).date()
    expired = [entry.fingerprint for entry in policy.entries if entry.expires_at < evaluation_date]
    if expired:
        raise SecretScanPolicyError("secret_scan_allowlist_entry_expired")
    overlong = [
        entry.fingerprint
        for entry in policy.entries
        if entry.expires_at > evaluation_date + MAX_ALLOWLIST_LIFETIME
    ]
    if overlong:
        raise SecretScanPolicyError("secret_scan_allowlist_expiry_exceeds_90_days")
    scopes = [
        (entry.fingerprint, entry.path, entry.rule_id, entry.commit) for entry in policy.entries
    ]
    if len(scopes) != len(set(scopes)):
        raise SecretScanPolicyError("secret_scan_allowlist_scope_duplicated")
    return policy


def _finding_scope(finding: dict[str, Any]) -> tuple[str, str, str, str]:
    fingerprint = finding.get("Fingerprint")
    path = finding.get("File")
    rule_id = finding.get("RuleID")
    commit = finding.get("Commit")
    if (
        not isinstance(fingerprint, str)
        or not fingerprint
        or not isinstance(path, str)
        or not path
        or not isinstance(rule_id, str)
        or not rule_id
        or not isinstance(commit, str)
        or not commit
    ):
        raise SecretScanPolicyError("gitleaks_finding_scope_invalid")
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise SecretScanPolicyError("gitleaks_finding_commit_invalid")
    return fingerprint, path, rule_id, commit


def evaluate_report(
    findings: list[Any],
    policy: SecretScanAllowlist,
    *,
    scanner_version: str,
) -> tuple[dict[str, Any], bool]:
    """Return redacted evidence and whether every finding has one exact active exception."""

    allowed_scopes = {
        (entry.fingerprint, entry.path, entry.rule_id, entry.commit): entry
        for entry in policy.entries
    }
    used_scopes: set[tuple[str, str, str, str]] = set()
    safe_findings: list[dict[str, Any]] = []
    unaccepted = 0
    for raw_finding in findings:
        if not isinstance(raw_finding, dict):
            raise SecretScanPolicyError("gitleaks_finding_not_object")
        scope = _finding_scope(raw_finding)
        entry = allowed_scopes.get(scope)
        accepted = entry is not None
        if accepted:
            used_scopes.add(scope)
        else:
            unaccepted += 1
        start_line = raw_finding.get("StartLine")
        if not isinstance(start_line, int) or start_line < 1:
            raise SecretScanPolicyError("gitleaks_finding_line_invalid")
        if scope[0] != f"{scope[3]}:{scope[1]}:{scope[2]}:{start_line}":
            raise SecretScanPolicyError("gitleaks_finding_fingerprint_inconsistent")
        safe_findings.append(
            {
                "commit": scope[3],
                "fingerprint": scope[0],
                "line": start_line,
                "path": scope[1],
                "rule_id": scope[2],
                "status": "allowlisted" if accepted else "unaccepted",
            }
        )
    unused = set(allowed_scopes) - used_scopes
    passed = unaccepted == 0 and not unused
    evidence = {
        "schema_version": "modelguard.secret-scan-evidence.v1",
        "scanner": {"name": "gitleaks", "version": scanner_version, "redaction": "100%"},
        "history_scope": "all_refs_available_in_full_checkout",
        "status": "passed" if passed else "failed",
        "finding_count": len(safe_findings),
        "allowlisted_count": len(used_scopes),
        "unaccepted_count": unaccepted,
        "unused_allowlist_count": len(unused),
        "findings": sorted(
            safe_findings,
            key=lambda item: (item["path"], item["line"], item["rule_id"], item["commit"]),
        ),
    }
    return evidence, passed


def process_report(
    *,
    report_path: Path,
    allowlist_path: Path,
    output_path: Path,
    scanner_version: str,
    today: date | None = None,
) -> bool:
    """Evaluate a redacted raw report, write minimal evidence, and return gate status."""

    raw_report = _load_json(report_path)
    if not isinstance(raw_report, list):
        raise SecretScanPolicyError("gitleaks_report_root_not_array")
    policy = load_allowlist(allowlist_path, today=today)
    evidence, passed = evaluate_report(raw_report, policy, scanner_version=scanner_version)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return passed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="secret-scan-policy")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--allowlist", type=Path, required=True)
    report = subparsers.add_parser("report")
    report.add_argument("--input", type=Path, required=True)
    report.add_argument("--allowlist", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    report.add_argument("--scanner-version", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "validate":
            policy = load_allowlist(args.allowlist)
            print(json.dumps({"status": "passed", "entries": len(policy.entries)}))
            return 0
        passed = process_report(
            report_path=args.input,
            allowlist_path=args.allowlist,
            output_path=args.output,
            scanner_version=args.scanner_version,
        )
        print(json.dumps({"status": "passed" if passed else "failed"}))
        return 0 if passed else 1
    except (OSError, json.JSONDecodeError, ValidationError, SecretScanPolicyError) as error:
        reason = str(error).splitlines()[0][:160]
        print(json.dumps({"status": "refused", "reason": reason}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
