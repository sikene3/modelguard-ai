#!/usr/bin/env python3
"""Fail on unaccepted critical Trivy image findings and summarize bounded exceptions."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from modelguard.core.serialization import load_strict_json

IMAGE_NAMES = (
    "modelguard-api:local",
    "modelguard-dashboard:local",
    "modelguard-monitor:local",
)


class ScanEvaluationError(ValueError):
    """The scan or exception contract was invalid or did not pass policy."""


@dataclass(frozen=True)
class CriticalFinding:
    image: str
    vulnerability_id: str
    package_name: str
    installed_version: str
    fixed_version: str
    target: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.image, self.vulnerability_id, self.package_name)


@dataclass(frozen=True)
class ScanException:
    image: str
    vulnerability_id: str
    package_name: str
    rationale: str
    owner: str
    expires_on: date

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.image, self.vulnerability_id, self.package_name)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="append", type=Path, required=True)
    parser.add_argument(
        "--exceptions",
        type=Path,
        default=Path("configs/trivy-exceptions.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat)
    return parser


def _load_json(path: Path) -> Any:
    try:
        return load_strict_json(path)
    except (OSError, UnicodeError, ValueError) as error:
        raise ScanEvaluationError(f"invalid JSON: {path.name}") from error


def _scan_findings(path: Path) -> tuple[str, list[CriticalFinding]]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ScanEvaluationError(f"scan root must be an object: {path.name}")
    image = payload.get("ArtifactName")
    if image not in IMAGE_NAMES:
        raise ScanEvaluationError(f"scan image identity is unsupported: {path.name}")
    results = payload.get("Results", [])
    if not isinstance(results, list):
        raise ScanEvaluationError(f"scan results must be a list: {path.name}")
    findings: list[CriticalFinding] = []
    for result in results:
        if not isinstance(result, dict):
            raise ScanEvaluationError(f"scan result must be an object: {path.name}")
        target = str(result.get("Target", "unknown"))
        vulnerabilities = result.get("Vulnerabilities") or []
        if not isinstance(vulnerabilities, list):
            raise ScanEvaluationError(f"scan vulnerabilities must be a list: {path.name}")
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                raise ScanEvaluationError(f"scan vulnerability must be an object: {path.name}")
            if vulnerability.get("Severity") != "CRITICAL":
                continue
            vulnerability_id = vulnerability.get("VulnerabilityID")
            package_name = vulnerability.get("PkgName")
            if not isinstance(vulnerability_id, str) or not vulnerability_id:
                raise ScanEvaluationError("critical finding lacks VulnerabilityID")
            if not isinstance(package_name, str) or not package_name:
                raise ScanEvaluationError("critical finding lacks PkgName")
            findings.append(
                CriticalFinding(
                    image=image,
                    vulnerability_id=vulnerability_id,
                    package_name=package_name,
                    installed_version=str(vulnerability.get("InstalledVersion", "")),
                    fixed_version=str(vulnerability.get("FixedVersion", "")),
                    target=target,
                )
            )
    return image, findings


def _exceptions(path: Path, *, as_of: date) -> list[ScanException]:
    payload = _load_json(path)
    if not isinstance(payload, dict) or payload.get("schema_version") != (
        "modelguard.trivy-exceptions.v1"
    ):
        raise ScanEvaluationError("Trivy exception schema version is invalid")
    raw_exceptions = payload.get("exceptions")
    if not isinstance(raw_exceptions, list):
        raise ScanEvaluationError("Trivy exceptions must be a list")
    allowed_fields = {
        "image",
        "vulnerability_id",
        "package_name",
        "rationale",
        "owner",
        "expires_on",
    }
    parsed: list[ScanException] = []
    for raw in raw_exceptions:
        if not isinstance(raw, dict) or set(raw) != allowed_fields:
            raise ScanEvaluationError("a Trivy exception has invalid fields")
        if raw["image"] not in IMAGE_NAMES:
            raise ScanEvaluationError("a Trivy exception has an invalid image")
        if not isinstance(raw["rationale"], str) or len(raw["rationale"].strip()) < 20:
            raise ScanEvaluationError("a Trivy exception rationale is too short")
        if not isinstance(raw["owner"], str) or not raw["owner"].strip():
            raise ScanEvaluationError("a Trivy exception owner is missing")
        try:
            expires_on = date.fromisoformat(str(raw["expires_on"]))
        except ValueError as error:
            raise ScanEvaluationError("a Trivy exception expiry is invalid") from error
        if expires_on < as_of:
            raise ScanEvaluationError("a Trivy exception is expired")
        if expires_on > as_of + timedelta(days=90):
            raise ScanEvaluationError("a Trivy exception exceeds the 90-day maximum")
        for name in ("vulnerability_id", "package_name"):
            if not isinstance(raw[name], str) or not raw[name]:
                raise ScanEvaluationError(f"a Trivy exception {name} is missing")
        parsed.append(
            ScanException(
                image=raw["image"],
                vulnerability_id=raw["vulnerability_id"],
                package_name=raw["package_name"],
                rationale=raw["rationale"].strip(),
                owner=raw["owner"].strip(),
                expires_on=expires_on,
            )
        )
    keys = [exception.key for exception in parsed]
    if len(keys) != len(set(keys)):
        raise ScanEvaluationError("duplicate Trivy exceptions are forbidden")
    return parsed


def evaluate(
    scan_paths: list[Path],
    exception_path: Path,
    *,
    as_of: date,
) -> dict[str, Any]:
    if len(scan_paths) != len(IMAGE_NAMES):
        raise ScanEvaluationError("exactly three image scans are required")
    scans: dict[str, list[CriticalFinding]] = {}
    for scan_path in scan_paths:
        image, findings = _scan_findings(scan_path)
        if image in scans:
            raise ScanEvaluationError("duplicate image scans are forbidden")
        scans[image] = findings
    if set(scans) != set(IMAGE_NAMES):
        raise ScanEvaluationError("the scan set does not cover all three images")

    exceptions = _exceptions(exception_path, as_of=as_of)
    findings_by_key = {finding.key: finding for findings in scans.values() for finding in findings}
    exceptions_by_key = {exception.key: exception for exception in exceptions}
    unused = sorted(set(exceptions_by_key) - set(findings_by_key))
    if unused:
        raise ScanEvaluationError("a Trivy exception is stale or does not match a finding")
    unaccepted = sorted(set(findings_by_key) - set(exceptions_by_key))
    summary = {
        "schema_version": "modelguard.trivy-scan-summary.v1",
        "status": "passed" if not unaccepted else "failed",
        "evaluated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "policy_as_of": as_of.isoformat(),
        "images": {
            image: {
                "critical_findings": len(scans[image]),
                "accepted_exceptions": sum(
                    1 for finding in scans[image] if finding.key in exceptions_by_key
                ),
                "unaccepted_findings": sum(
                    1 for finding in scans[image] if finding.key not in exceptions_by_key
                ),
            }
            for image in IMAGE_NAMES
        },
        "accepted_exceptions": [
            {
                "image": exception.image,
                "vulnerability_id": exception.vulnerability_id,
                "package_name": exception.package_name,
                "owner": exception.owner,
                "rationale": exception.rationale,
                "expires_on": exception.expires_on.isoformat(),
            }
            for exception in exceptions
        ],
        "unaccepted_findings": [
            {
                "image": finding.image,
                "vulnerability_id": finding.vulnerability_id,
                "package_name": finding.package_name,
                "installed_version": finding.installed_version,
                "fixed_version": finding.fixed_version,
                "target": finding.target,
            }
            for key, finding in sorted(findings_by_key.items())
            if key in unaccepted
        ],
    }
    return summary


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ScanEvaluationError("scan summary path is unsafe")
    payload = json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    arguments = _parser().parse_args()
    try:
        summary = evaluate(
            arguments.scan,
            arguments.exceptions,
            as_of=arguments.as_of or datetime.now(UTC).date(),
        )
        _atomic_write(arguments.output, summary)
    except (OSError, ScanEvaluationError, ValueError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(summary, allow_nan=False, separators=(",", ":"), sort_keys=True))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
