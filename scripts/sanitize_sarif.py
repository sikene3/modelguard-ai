#!/usr/bin/env python3
"""Create value-free SARIF from scanner output before GitHub Code Scanning upload."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

ALLOWED_LEVELS = frozenset({"none", "note", "warning", "error"})
RULE_PATTERN = re.compile(r"^[A-Za-z0-9_.:/@+-]{1,200}$")


class SarifSanitizationError(ValueError):
    """A scanner artifact could not be sanitized safely."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SarifSanitizationError(f"invalid scanner JSON: {path.name}") from error


def _safe_rule(value: Any) -> str:
    if not isinstance(value, str) or RULE_PATTERN.fullmatch(value) is None:
        raise SarifSanitizationError("scanner finding has an unsafe rule ID")
    return value


def _safe_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise SarifSanitizationError("scanner finding has an invalid path")
    normalized = value.replace("\\", "/")
    for prefix in ("file:///workspace/", "/workspace/", "file://"):
        if normalized.startswith(prefix):
            normalized = normalized.removeprefix(prefix)
            break
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(ord(character) < 32 for character in normalized)
    ):
        raise SarifSanitizationError("scanner finding path escapes the repository")
    return path.as_posix()


def _safe_line(value: Any) -> int:
    if not isinstance(value, int) or value < 1 or value > 10_000_000:
        raise SarifSanitizationError("scanner finding has an invalid line")
    return value


def _location(uri: str, line: int, column: int | None = None) -> dict[str, Any]:
    region: dict[str, int] = {"startLine": line}
    if isinstance(column, int) and 1 <= column <= 100_000:
        region["startColumn"] = column
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": uri, "uriBaseId": "%SRCROOT%"},
            "region": region,
        }
    }


def _driver(scanner: str, rules: set[str]) -> dict[str, Any]:
    return {
        "name": scanner,
        "rules": [
            {
                "id": rule,
                "shortDescription": {"text": f"{scanner} security rule {rule}"},
            }
            for rule in sorted(rules)
        ],
    }


def _sarif(scanner: str, results: list[dict[str, Any]], rules: set[str]) -> dict[str, Any]:
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{"tool": {"driver": _driver(scanner, rules)}, "results": results}],
    }


def sanitize_sarif(payload: Any, *, scanner: str) -> dict[str, Any]:
    """Drop messages, snippets, environment data, and properties from an existing SARIF file."""

    if not isinstance(payload, dict) or payload.get("version") != "2.1.0":
        raise SarifSanitizationError("scanner SARIF version is unsupported")
    raw_runs = payload.get("runs")
    if not isinstance(raw_runs, list):
        raise SarifSanitizationError("scanner SARIF runs must be a list")
    results: list[dict[str, Any]] = []
    rules: set[str] = set()
    for run in raw_runs:
        if not isinstance(run, dict):
            raise SarifSanitizationError("scanner SARIF run is invalid")
        raw_results = run.get("results", [])
        if not isinstance(raw_results, list):
            raise SarifSanitizationError("scanner SARIF results must be a list")
        for raw in raw_results:
            if not isinstance(raw, dict):
                raise SarifSanitizationError("scanner SARIF result is invalid")
            rule = _safe_rule(raw.get("ruleId"))
            level = raw.get("level", "warning")
            if level not in ALLOWED_LEVELS:
                level = "warning"
            raw_suppressions = raw.get("suppressions", [])
            if not isinstance(raw_suppressions, list):
                raise SarifSanitizationError("scanner SARIF suppressions must be a list")
            safe: dict[str, Any] = {
                "ruleId": rule,
                "level": "note" if raw_suppressions else level,
                "message": {"text": f"{scanner} reported security rule {rule}."},
            }
            if raw_suppressions:
                if any(
                    not isinstance(suppression, dict) or suppression.get("kind") != "inSource"
                    for suppression in raw_suppressions
                ):
                    raise SarifSanitizationError("scanner SARIF suppression kind is unsupported")
                safe["suppressions"] = [
                    {
                        "kind": "inSource",
                        "justification": (
                            "Version-controlled suppression metadata passed repository policy."
                        ),
                    }
                ]
            raw_locations = raw.get("locations", [])
            if not isinstance(raw_locations, list):
                raise SarifSanitizationError("scanner SARIF locations must be a list")
            locations: list[dict[str, Any]] = []
            for raw_location in raw_locations[:1]:
                if not isinstance(raw_location, dict):
                    continue
                physical = raw_location.get("physicalLocation")
                if not isinstance(physical, dict):
                    continue
                artifact = physical.get("artifactLocation")
                region = physical.get("region")
                if not isinstance(artifact, dict) or not isinstance(region, dict):
                    continue
                locations.append(
                    _location(
                        _safe_path(artifact.get("uri")),
                        _safe_line(region.get("startLine", 1)),
                        region.get("startColumn"),
                    )
                )
            if locations:
                safe["locations"] = locations
            results.append(safe)
            rules.add(rule)
    return _sarif(scanner, results, rules)


def gitleaks_evidence_to_sarif(payload: Any, *, scanner: str = "gitleaks") -> dict[str, Any]:
    """Convert the existing value-free Gitleaks evidence into minimal SARIF."""

    if not isinstance(payload, dict) or payload.get("schema_version") != (
        "modelguard.secret-scan-evidence.v1"
    ):
        raise SarifSanitizationError("Gitleaks evidence schema is unsupported")
    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list):
        raise SarifSanitizationError("Gitleaks evidence findings must be a list")
    results: list[dict[str, Any]] = []
    rules: set[str] = set()
    for raw in raw_findings:
        if not isinstance(raw, dict):
            raise SarifSanitizationError("Gitleaks evidence finding is invalid")
        rule = _safe_rule(raw.get("rule_id"))
        path = _safe_path(raw.get("path"))
        line = _safe_line(raw.get("line"))
        status = raw.get("status")
        if status not in {"allowlisted", "unaccepted"}:
            raise SarifSanitizationError("Gitleaks evidence status is invalid")
        results.append(
            {
                "ruleId": rule,
                "level": "note" if status == "allowlisted" else "error",
                "message": {"text": f"gitleaks reported {rule}; status={status}."},
                "locations": [_location(path, line)],
            }
        )
        rules.add(rule)
    return _sarif(scanner, results, rules)


def gitleaks_raw_to_sarif(payload: Any, *, scanner: str = "gitleaks-worktree") -> dict[str, Any]:
    """Convert 100%-redacted worktree results without retaining matched values."""

    if not isinstance(payload, list):
        raise SarifSanitizationError("Gitleaks worktree report must be a list")
    results: list[dict[str, Any]] = []
    rules: set[str] = set()
    for raw in payload:
        if not isinstance(raw, dict):
            raise SarifSanitizationError("Gitleaks worktree finding is invalid")
        rule = _safe_rule(raw.get("RuleID"))
        path = _safe_path(raw.get("File"))
        line = _safe_line(raw.get("StartLine"))
        results.append(
            {
                "ruleId": rule,
                "level": "error",
                "message": {"text": f"gitleaks reported {rule} in the working tree."},
                "locations": [_location(path, line)],
            }
        )
        rules.add(rule)
    return _sarif(scanner, results, rules)


def cyclonedx_to_sarif(payload: Any, *, scanner: str = "trivy-image") -> dict[str, Any]:
    """Create value-free image SARIF from one Trivy CycloneDX result."""

    if not isinstance(payload, dict) or payload.get("bomFormat") != "CycloneDX":
        raise SarifSanitizationError("Trivy CycloneDX report is invalid")
    vulnerabilities = payload.get("vulnerabilities", [])
    if not isinstance(vulnerabilities, list):
        raise SarifSanitizationError("Trivy CycloneDX vulnerabilities must be a list")
    results: list[dict[str, Any]] = []
    rules: set[str] = set()
    for raw in vulnerabilities:
        if not isinstance(raw, dict):
            raise SarifSanitizationError("Trivy CycloneDX vulnerability is invalid")
        rule = _safe_rule(raw.get("id"))
        severities = {
            str(rating.get("severity", "")).lower()
            for rating in raw.get("ratings", [])
            if isinstance(rating, dict)
        }
        if not severities & {"high", "critical"}:
            continue
        results.append(
            {
                "ruleId": rule,
                "level": "error",
                "message": {"text": f"trivy reported image vulnerability {rule}."},
            }
        )
        rules.add(rule)
    return _sarif(scanner, results, rules)


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, allow_nan=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["sarif", "gitleaks-evidence", "gitleaks-raw", "cyclonedx"])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scanner", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        payload = _read_json(args.input)
        if args.mode == "sarif":
            result = sanitize_sarif(payload, scanner=args.scanner)
        elif args.mode == "gitleaks-evidence":
            result = gitleaks_evidence_to_sarif(payload, scanner=args.scanner)
        elif args.mode == "gitleaks-raw":
            result = gitleaks_raw_to_sarif(payload, scanner=args.scanner)
        else:
            result = cyclonedx_to_sarif(payload, scanner=args.scanner)
        _atomic_write(args.output, result)
    except (OSError, UnicodeError, SarifSanitizationError, ValueError) as error:
        print(json.dumps({"status": "refused", "reason": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps({"status": "sanitized", "output": args.output.name}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
