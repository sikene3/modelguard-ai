from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import tarfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from scripts.sanitize_sarif import sanitize_sarif
from scripts.security_gate_runner import REQUIRED_GATES, run_gates
from scripts.security_policy import SecurityPolicyError, validate
from scripts.security_tools import SecurityToolError, check, load_lock

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
LOCK = ROOT / "security" / "security-tools.lock.json"


def _workflow(name: str) -> dict[str, Any]:
    payload = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_lock(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_tool_lock_is_the_exact_complete_source_of_truth() -> None:
    lock = load_lock(LOCK)
    assert lock["platform"] == "linux-x86_64"
    assert set(lock["tools"]) == {
        "actionlint",
        "shellcheck",
        "checkov",
        "trivy",
        "gitleaks",
    }
    assert {name: raw["version"] for name, raw in lock["tools"].items()} == {
        "actionlint": "1.7.9",
        "shellcheck": "0.11.0",
        "checkov": "3.3.9",
        "trivy": "0.70.0",
        "gitleaks": "8.30.1",
    }
    for raw in lock["tools"].values():
        if raw["kind"] == "archive":
            assert re.fullmatch(r"[0-9a-f]{64}", raw["sha256"])
        else:
            assert re.fullmatch(r".+:[0-9.]+@sha256:[0-9a-f]{64}", raw["image"])


@pytest.mark.parametrize("mutation", ["latest-version", "latest-image", "missing-digest"])
def test_tool_lock_rejects_mutable_or_unverified_inputs(tmp_path: Path, mutation: str) -> None:
    payload = copy.deepcopy(json.loads(LOCK.read_text(encoding="utf-8")))
    if mutation == "latest-version":
        payload["tools"]["actionlint"]["version"] = "latest"
    elif mutation == "latest-image":
        payload["tools"]["checkov"]["image"] = (
            "docker.io/bridgecrew/checkov:latest@sha256:" + "a" * 64
        )
    else:
        payload["tools"]["checkov"]["image"] = "docker.io/bridgecrew/checkov:3.3.9"
    path = tmp_path / "security-tools.lock.json"
    _write_lock(path, payload)
    with pytest.raises(SecurityToolError):
        load_lock(path)


def test_missing_repository_local_scanner_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODELGUARD_SECURITY_TOOLS_TEST_OVERRIDE", "1")
    monkeypatch.setenv("SECURITY_TOOLS_CACHE", str(tmp_path / "missing-cache"))
    with pytest.raises(SecurityToolError, match=r"missing|another lock|invalid security tool lock"):
        check(LOCK)


def test_cached_binary_must_match_the_checksum_verified_archive_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved_binary = tmp_path / "approved-actionlint"
    approved_binary.write_text("#!/bin/sh\necho actionlint version 1.7.9\n", encoding="utf-8")
    archive = tmp_path / "actionlint_1.7.9_linux_amd64.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(approved_binary, arcname="actionlint")

    payload = copy.deepcopy(json.loads(LOCK.read_text(encoding="utf-8")))
    payload["tools"]["actionlint"]["sha256"] = _sha256(archive)
    lock_path = tmp_path / "security-tools.lock.json"
    _write_lock(lock_path, payload)

    cache = tmp_path / "cache"
    binary = cache / "bin" / "actionlint"
    cached_archive = cache / "downloads" / archive.name
    binary.parent.mkdir(parents=True)
    cached_archive.parent.mkdir(parents=True)
    binary.write_bytes(approved_binary.read_bytes())
    binary.chmod(0o755)
    cached_archive.write_bytes(archive.read_bytes())
    state = {
        "schema_version": "modelguard.security-tools-state.v1",
        "lock_sha256": _sha256(lock_path),
        "tools": {
            "actionlint": {
                "archive_sha256": _sha256(cached_archive),
                "binary_sha256": _sha256(binary),
            }
        },
    }
    state_path = cache / "install-state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setenv("MODELGUARD_SECURITY_TOOLS_TEST_OVERRIDE", "1")
    monkeypatch.setenv("SECURITY_TOOLS_CACHE", str(cache))
    assert check(lock_path, only="actionlint") == {"actionlint": "1.7.9"}

    binary.write_text("#!/bin/sh\necho modified actionlint 1.7.9\n", encoding="utf-8")
    binary.chmod(0o755)
    state["tools"]["actionlint"]["binary_sha256"] = _sha256(binary)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(SecurityToolError, match="integrity"):
        check(lock_path, only="actionlint")


def test_gate_runner_invokes_every_scanner_and_propagates_nonzero() -> None:
    calls: list[str] = []

    def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command[-1])
        return subprocess.CompletedProcess(command, 9 if command[-1] == "checkov" else 0)

    commands = {name: ["security-scan", name] for name in REQUIRED_GATES}
    statuses, passed = run_gates(commands, runner=runner)
    assert calls == list(REQUIRED_GATES)
    assert statuses["checkov"] == 9
    assert passed is False


def test_gate_runner_treats_missing_executable_as_failure() -> None:
    def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if command[-1] == "gitleaks":
            raise FileNotFoundError(command[0])
        return subprocess.CompletedProcess(command, 0)

    commands = {name: ["security-scan", name] for name in REQUIRED_GATES}
    statuses, passed = run_gates(commands, runner=runner)
    assert statuses["gitleaks"] == 127
    assert passed is False


def test_make_targets_and_shared_scanner_commands_are_fail_closed() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "security_scan.sh").read_text(encoding="utf-8")
    shell_check = (ROOT / "scripts" / "check_shell.sh").read_text(encoding="utf-8")
    for target in ("security-tools-check", "security-scan", "release-gates"):
        assert re.search(rf"^{re.escape(target)}(?:\s*:[^\n]*)?$", makefile, re.MULTILINE)
    assert "security-scan: security-tools-check" in makefile
    assert "release-gates: verify security-scan" in makefile
    assert makefile.count("uv run --frozen --no-sync python -m scripts.security_tools") >= 2
    assert '-shellcheck "$shellcheck_bin"' in script
    assert "--framework terraform dockerfile github_actions" in script
    assert "--log-opts=--all" in script
    assert "security_tools version gitleaks" in script
    assert "--scanner-version 8.30.1" not in script
    assert "git ls-files --cached --others --exclude-standard" in script
    assert script.count("--severity HIGH,CRITICAL --exit-code 1") >= 3
    assert "skipped_unavailable" not in shell_check
    assert "command -v shellcheck" not in shell_check


def test_release_build_cannot_override_the_reviewed_digest_pinned_base() -> None:
    publisher = (WORKFLOWS / "publish-images.yml").read_text(encoding="utf-8")
    containers = (WORKFLOWS / "container-security.yml").read_text(encoding="utf-8")
    for workflow in (publisher, containers):
        assert "--build-arg PYTHON_BASE_IMAGE" not in workflow
        assert '--build-arg "PYTHON_BASE_IMAGE' not in workflow
    for component in ("api", "dashboard", "monitor"):
        dockerfile = (ROOT / "docker" / f"{component}.Dockerfile").read_text(encoding="utf-8")
        assert re.search(
            r"^ARG PYTHON_BASE_IMAGE=[^\s]+@sha256:[0-9a-f]{64}$", dockerfile, re.MULTILINE
        )


def test_production_cache_location_cannot_be_overridden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SECURITY_TOOLS_CACHE", str(tmp_path / "external"))
    monkeypatch.delenv("MODELGUARD_SECURITY_TOOLS_TEST_OVERRIDE", raising=False)
    with pytest.raises(SecurityToolError, match="isolated tests"):
        check(LOCK, only="actionlint")


def test_every_external_action_matches_the_pin_registry_and_release_comment() -> None:
    lock = load_lock(LOCK)
    pins = lock["github_actions"]
    seen: set[str] = set()
    pattern = re.compile(
        r"^\s*uses:\s*([^@\s]+)@([0-9a-f]{40})\s+#\s+v([0-9]+\.[0-9]+\.[0-9]+)\s*$"
    )
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "uses:" not in line or "uses: ./" in line:
                continue
            match = pattern.fullmatch(line)
            assert match is not None, f"unversioned external action in {path.name}: {line}"
            name, commit, version = match.groups()
            assert pins[name] == {"version": version, "commit": commit}
            seen.add(name)
    assert seen == set(pins)


def test_security_jobs_have_no_aws_or_deployment_authority() -> None:
    ci_security = _workflow("ci.yml")["jobs"]["security"]
    container_security = _workflow("container-security.yml")["jobs"]["build-and-scan"]
    publish_build = _workflow("publish-images.yml")["jobs"]["build-scan"]
    for job in (ci_security, container_security, publish_build):
        assert job["permissions"] == {"contents": "read", "security-events": "write"}
        assert "environment" not in job
        serialized = json.dumps(job)
        assert "id-token" not in serialized
        assert "secrets." not in serialized
        assert "configure-aws-credentials" not in serialized
        assert "terraform apply" not in serialized
        assert "aws ecr" not in serialized

    publisher = _workflow("publish-images.yml")["jobs"]["publish"]
    publisher_text = json.dumps(publisher)
    assert publisher["permissions"] == {
        "actions": "read",
        "contents": "read",
        "id-token": "write",
    }
    assert "security_scan.sh" not in publisher_text
    assert "github/codeql-action" not in publisher_text


def test_workflows_use_shared_policy_without_soft_failure() -> None:
    all_workflows = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(WORKFLOWS.glob("*.yml"))
    )
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    containers = (WORKFLOWS / "container-security.yml").read_text(encoding="utf-8")
    publisher = (WORKFLOWS / "publish-images.yml").read_text(encoding="utf-8")
    assert "make security-tools-bootstrap" in ci
    assert "make security-scan" in ci
    assert "./scripts/security_scan.sh image" in containers
    assert "./scripts/security_scan.sh image" in publisher
    assert "continue-on-error" not in all_workflows
    assert "soft-fail" not in all_workflows
    assert re.search(r"exit-code[=: ]+[\"']?0", all_workflows) is None


def test_image_scan_and_transfer_bind_exact_content_digest_before_aws() -> None:
    workflow = _workflow("publish-images.yml")
    source = (WORKFLOWS / "publish-images.yml").read_text(encoding="utf-8")
    build = json.dumps(workflow["jobs"]["build-scan"])
    publish = json.dumps(workflow["jobs"]["publish"])
    assert "{{.Id}}" in build
    assert '--image "$image_id"' in source
    assert "images.tar" in build
    assert "archive_sha256" in build
    assert "transfer_manifest_sha256" in publish
    assert "docker load" in publish
    assert 'test "$actual_id" = "$expected_id"' in source
    assert source.index("Verify and load only the exact scanned image transfer") < source.index(
        "configure-aws-credentials"
    )


def test_suppression_registry_is_exact_owned_and_time_bounded() -> None:
    counts = validate(ROOT, as_of=date(2026, 8, 4))
    assert counts == {"checkov": 50, "shellcheck": 6, "trivy": 3, "gitleaks": 1}
    with pytest.raises((SecurityPolicyError, ValueError), match="expired"):
        validate(ROOT, as_of=date(2026, 11, 1))


def test_new_bandit_suppressions_are_adjacent_owned_and_expiring() -> None:
    for relative in (
        "scripts/security_gate_runner.py",
        "scripts/security_policy.py",
        "scripts/security_tools.py",
    ):
        lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "# nosec" not in line:
                continue
            assert index >= 5
            block = [item.strip() for item in lines[index - 5 : index]]
            assert block[0] == "# security-suppression:"
            fields = dict(item.removeprefix("# ").split("=", 1) for item in block[1:])
            assert set(fields) == {"finding", "justification", "owner", "expires"}
            assert len(fields["justification"]) >= 20
            assert fields["owner"] == "modelguard-maintainers"
            assert fields["expires"] == "2026-10-31"
            nosec_ids = set(re.findall(r"B[0-9]+", line.split("# nosec", 1)[1]))
            assert set(fields["finding"].split(",")) == nosec_ids


def test_sarif_sanitizer_drops_messages_snippets_and_properties() -> None:
    payload = {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "scanner"}},
                "results": [
                    {
                        "ruleId": "RULE-1",
                        "level": "error",
                        "message": {"text": "actual-secret-value"},
                        "properties": {"environment": "actual-secret-value"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": "/workspace/src/example.py"},
                                    "region": {
                                        "startLine": 7,
                                        "snippet": {"text": "actual-secret-value"},
                                    },
                                }
                            }
                        ],
                    }
                ],
            }
        ],
    }
    safe = sanitize_sarif(payload, scanner="scanner")
    serialized = json.dumps(safe)
    assert "actual-secret-value" not in serialized
    assert "properties" not in serialized
    assert "snippet" not in serialized
    assert (
        safe["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        == "src/example.py"
    )
