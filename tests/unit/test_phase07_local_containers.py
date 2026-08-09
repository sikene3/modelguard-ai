"""Phase 07 container, Compose, traffic, evidence, and scan-policy tests."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess  # nosec B404 - fixed local bash syntax check only
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from scripts.evaluate_trivy_scan import ScanEvaluationError, evaluate
from scripts.generate_local_traffic import build_payloads, shift_features, validate_local_url
from scripts.validate_local_evidence import (
    EvidenceError,
    validate_corrupt_bundle,
    validate_sink_outage,
)

IMAGES = ("modelguard-api:local", "modelguard-dashboard:local", "modelguard-monitor:local")
DOCKERFILES = {
    "api": "docker-api",
    "dashboard": "docker-dashboard",
    "monitor": "docker-monitor",
}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _scan(path: Path, image: str, vulnerabilities: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(
        path,
        {
            "ArtifactName": image,
            "Results": [
                {
                    "Target": "python:3.12-alpine3.23",
                    "Vulnerabilities": vulnerabilities,
                }
            ],
        },
    )
    return path


def _scan_set(tmp_path: Path, *, finding: bool) -> list[Path]:
    vulnerability = {
        "VulnerabilityID": "CVE-2099-0001",
        "PkgName": "example-package",
        "InstalledVersion": "1.0",
        "FixedVersion": "1.1",
        "Severity": "CRITICAL",
    }
    return [
        _scan(
            tmp_path / f"{index}.json",
            image,
            [vulnerability] if finding and index == 0 else [],
        )
        for index, image in enumerate(IMAGES)
    ]


def test_traffic_payloads_are_deterministic_schema_bounded_and_strongly_shifted() -> None:
    baseline = build_payloads(scenario="baseline", row_count=8, seed=8_080)
    repeated = build_payloads(scenario="baseline", row_count=8, seed=8_080)
    drifted = build_payloads(scenario="drifted", row_count=8, seed=8_080)

    assert baseline == repeated
    assert len(baseline) == len(drifted) == 8
    assert all(set(payload) == set(baseline[0]) for payload in baseline)
    assert all(payload["country_code"] == "BR" for payload in drifted)
    assert all(payload["device_type"] == "tablet" for payload in drifted)
    assert all(payload["is_new_device"] is True for payload in drifted)
    assert all(0.01 <= float(payload["amount"]) <= 25_000.0 for payload in drifted)
    assert all(0 <= int(payload["velocity_1h"]) <= 30 for payload in drifted)
    assert drifted[0] == shift_features(baseline[0])


@pytest.mark.parametrize(
    "value",
    [
        "https://127.0.0.1:8000",
        "http://example.com:8000",
        "http://127.0.0.1:8000/v1/predict",
        "http://user:password@127.0.0.1:8000",
        "http://127.0.0.1:invalid",
    ],
)
def test_traffic_generator_rejects_non_origin_or_non_loopback_urls(value: str) -> None:
    with pytest.raises(ValueError, match=r"loopback|port"):
        validate_local_url(value)
    assert validate_local_url("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"


def test_trivy_evaluator_passes_clean_scans_and_rejects_unaccepted_critical(
    tmp_path: Path,
) -> None:
    exception_path = tmp_path / "exceptions.json"
    _write_json(
        exception_path,
        {"schema_version": "modelguard.trivy-exceptions.v1", "exceptions": []},
    )
    clean = evaluate(
        _scan_set(tmp_path / "clean", finding=False), exception_path, as_of=date(2026, 8, 2)
    )
    critical = evaluate(
        _scan_set(tmp_path / "critical", finding=True),
        exception_path,
        as_of=date(2026, 8, 2),
    )

    assert clean["status"] == "passed"
    assert critical["status"] == "failed"
    assert critical["unaccepted_findings"][0]["vulnerability_id"] == "CVE-2099-0001"


def test_trivy_exception_requires_exact_active_bounded_ownership_record(tmp_path: Path) -> None:
    scans = _scan_set(tmp_path / "scans", finding=True)
    exception_path = tmp_path / "exceptions.json"
    exception = {
        "image": "modelguard-api:local",
        "vulnerability_id": "CVE-2099-0001",
        "package_name": "example-package",
        "rationale": "No fixed package is available; exposure is locally bounded.",
        "owner": "modelguard-maintainer",
        "expires_on": "2026-09-01",
    }
    _write_json(
        exception_path,
        {"schema_version": "modelguard.trivy-exceptions.v1", "exceptions": [exception]},
    )
    accepted = evaluate(scans, exception_path, as_of=date(2026, 8, 2))
    assert accepted["status"] == "passed"
    assert accepted["images"]["modelguard-api:local"]["accepted_exceptions"] == 1

    exception["expires_on"] = "2027-01-01"
    _write_json(
        exception_path,
        {"schema_version": "modelguard.trivy-exceptions.v1", "exceptions": [exception]},
    )
    with pytest.raises(ScanEvaluationError, match="90-day"):
        evaluate(scans, exception_path, as_of=date(2026, 8, 2))


def test_failure_evidence_validators_prove_corrupt_bundle_and_fail_open_sink(
    tmp_path: Path,
) -> None:
    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    (corrupt / "live.status").write_text("200\n", encoding="utf-8")
    (corrupt / "ready.status").write_text("503\n", encoding="utf-8")
    (corrupt / "version.status").write_text("200\n", encoding="utf-8")
    (corrupt / "predict.status").write_text("503\n", encoding="utf-8")
    _write_json(corrupt / "ready.json", {"status": "not_ready"})
    _write_json(
        corrupt / "version.json",
        {
            "service_version": "0.1.0",
            "model_ready": False,
            "model_version": None,
            "manifest_sha256": None,
        },
    )
    _write_json(corrupt / "predict.json", {"code": "model_not_ready"})
    assert validate_corrupt_bundle(corrupt)["status"] == "passed"

    sink = tmp_path / "sink"
    sink.mkdir()
    (sink / "ready.status").write_text("200\n", encoding="utf-8")
    (sink / "predict.status").write_text("200\n", encoding="utf-8")
    _write_json(sink / "predict.json", {"risk_score": 0.5})
    (sink / "metrics.prom").write_text(
        'modelguard_event_sink_operations_total{outcome="local_failed"} 1.0\n'
        'modelguard_errors_total{kind="event_sink"} 1.0\n',
        encoding="utf-8",
    )
    assert validate_sink_outage(sink)["status"] == "passed"

    _write_json(corrupt / "version.json", [])
    with pytest.raises(EvidenceError, match="root must be an object"):
        validate_corrupt_bundle(corrupt)


def test_dockerfiles_are_digest_pinned_minimal_labeled_non_root_and_healthy(
    repository_root: Path,
) -> None:
    lock_digest = (
        __import__("hashlib").sha256((repository_root / "uv.lock").read_bytes()).hexdigest()
    )
    for component, group in DOCKERFILES.items():
        dockerfile = repository_root / "docker" / f"{component}.Dockerfile"
        content = dockerfile.read_text(encoding="utf-8")
        assert content.count("@sha256:") == 1
        assert content.count("FROM ${PYTHON_BASE_IMAGE}") == 2
        assert f"--only-group {group}" in content
        assert "--frozen" in content
        assert "UV_HTTP_TIMEOUT=120" in content
        assert "type=cache,target=/root/.cache/uv,sharing=locked" in content
        assert "USER 10001:10001" in content
        assert "-perm -4000 -o -perm -2000" in content
        assert "HEALTHCHECK" in content
        if component == "api":
            assert 'CMD ["python", "-m", "uvicorn"' in content
        elif component == "dashboard":
            assert 'CMD ["python", "-m", "streamlit"' in content
            # Streamlit's Git integration is not used with the production file watcher
            # disabled. Exclude the unnecessary GitPython dependency chain from the image.
            assert "--no-install-package gitpython" in content
            assert "--no-install-package gitdb" in content
            assert "--no-install-package smmap" in content
        else:
            assert 'ENTRYPOINT ["python", "-m", "modelguard.monitoring.cli"]' in content
        assert 'org.opencontainers.image.revision="${SOURCE_REVISION}"' in content
        assert f"ARG UV_LOCK_SHA256={lock_digest}" in content
        assert 'io.modelguard.uv-lock.sha256="${UV_LOCK_SHA256}"' in content
        assert "COPY artifacts" not in content
        assert "COPY .env" not in content
        assert "docker.sock" not in content
        assert "latest" not in content.casefold()


def test_compose_is_local_only_non_root_hardened_and_uses_external_artifacts(
    repository_root: Path,
) -> None:
    compose_text = (repository_root / "docker-compose.yml").read_text(encoding="utf-8")
    compose = yaml.safe_load(compose_text)
    services = compose["services"]
    assert set(services) == {"api", "dashboard", "monitor"}
    assert services["monitor"]["scale"] == 0
    assert "profiles" not in services["monitor"]
    assert services["api"]["environment"]["EVENT_SINK"] == "local"
    assert services["monitor"]["environment"]["EVENT_SINK"] == "disabled"
    assert "docker.sock" not in compose_text
    assert "AWS_ACCESS_KEY" not in compose_text
    assert "AWS_SECRET" not in compose_text
    assert "amazonaws.com" not in compose_text
    assert "network_mode: host" not in compose_text
    for service in services.values():
        assert service["user"] == "10001:10001"
        assert service["read_only"] is True
        assert "init" not in service
        assert service["cap_drop"] == ["ALL"]
        assert "security_opt" not in service
        assert any(volume.get("target") == "/runtime" for volume in service["volumes"])
        model_mounts = [
            volume
            for volume in service["volumes"]
            if volume.get("target", "").startswith("/model/")
        ]
        assert len(model_mounts) == 7
        assert all(volume["type"] == "bind" and volume["read_only"] for volume in model_mounts)
        assert all(volume["bind"] == {"create_host_path": False} for volume in model_mounts)
    for component in ("dashboard", "monitor"):
        config_mounts = [
            volume
            for volume in services[component]["volumes"]
            if volume.get("target") == "/app/configs/phase-07-monitoring.json"
        ]
        assert config_mounts == [
            {
                "type": "bind",
                "source": "./configs/phase-07-monitoring.json",
                "target": "/app/configs/phase-07-monitoring.json",
                "read_only": True,
                "bind": {"create_host_path": False},
            }
        ]


def test_compose_and_dockerfile_lock_defaults_match_current_lock(repository_root: Path) -> None:
    lock_digest = (
        __import__("hashlib").sha256((repository_root / "uv.lock").read_bytes()).hexdigest()
    )
    compose = (repository_root / "docker-compose.yml").read_text(encoding="utf-8")
    match = re.search(r"UV_LOCK_SHA256:-([0-9a-f]{64})", compose)
    assert match is not None and match.group(1) == lock_digest
    base_match = re.search(r"PYTHON_BASE_IMAGE: (python:[^\s]+@sha256:[0-9a-f]{64})", compose)
    assert base_match is not None
    assert "${PYTHON_BASE_IMAGE" not in compose
    for component in DOCKERFILES:
        dockerfile = (repository_root / "docker" / f"{component}.Dockerfile").read_text(
            encoding="utf-8"
        )
        assert f"ARG PYTHON_BASE_IMAGE={base_match.group(1)}" in dockerfile


def test_docker_context_excludes_generated_sensitive_and_development_inputs(
    repository_root: Path,
) -> None:
    dockerignore_lines = (
        (repository_root / ".dockerignore").read_text(encoding="utf-8").splitlines()
    )
    ignored = set(dockerignore_lines)
    assert dockerignore_lines[0] == "**"
    assert {".git", ".env", "artifacts", "mlruns", "tests", "infrastructure"} <= ignored
    assert {
        "!pyproject.toml",
        "!uv.lock",
        "!README.md",
        "!src/",
        "!src/modelguard/",
        "!src/modelguard/**/",
        "!src/modelguard/**/*.py",
        "!src/modelguard/py.typed",
        "!.streamlit/",
        "!.streamlit/config.toml",
    } <= ignored
    assert "!.env.example" not in ignored
    groups = tomllib.loads((repository_root / "pyproject.toml").read_text(encoding="utf-8"))[
        "dependency-groups"
    ]
    assert set(DOCKERFILES.values()) <= set(groups)
    assert "pytest>=9.0.3,<10" in groups["dev"]
    assert all("pytest" not in str(groups[group]) for group in DOCKERFILES.values())


def test_phase07_shell_scripts_are_executable_and_bash_syntax_valid(
    repository_root: Path,
) -> None:
    phase_scripts = [
        "build_local_images.sh",
        "check_shell.sh",
        "demo_local.sh",
        "e2e_local.sh",
        "local_compose_lib.sh",
        "scan_local_images.sh",
        "smoke_local.sh",
    ]
    for filename in phase_scripts:
        path = repository_root / "scripts" / filename
        assert stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR
        subprocess.run(
            ["bash", "-n", os.fspath(path)],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
    compose_library = (repository_root / "scripts" / "local_compose_lib.sh").read_text(
        encoding="utf-8"
    )
    assert "date -u +%Y%m%dt%H%M%Sz" in compose_library
    assert '"$compose_major" -ge 2' in compose_library
    assert "modelguard_source_revision" in compose_library
    assert "modelguard_wait_metric" in compose_library
    for filename in ("smoke_local.sh", "demo_local.sh", "e2e_local.sh"):
        content = (repository_root / "scripts" / filename).read_text(encoding="utf-8")
        assert 'run_stamp="$(modelguard_utc_run_stamp)"' in content
