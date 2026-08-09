"""Phase 09 CI/CD identity, redaction, provenance, and trust-boundary gates."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError
from scripts.deployment_record import DeploymentRecord, DeploymentRecordError, create_record
from scripts.notification_enrollment import (
    NotificationEnrollmentError,
    enroll_notifications,
    verify_notification_enrollment,
)
from scripts.plan_evidence import render_markdown, summarize_plan
from scripts.release_manifest import (
    ImageRelease,
    ImageReleaseManifest,
    ReleaseManifestError,
    create_manifest,
    verify_manifest,
    verify_release_source,
)
from scripts.render_ci_terraform import RenderInputError, render_inputs
from scripts.secret_scan_policy import (
    SecretScanAllowlist,
    SecretScanPolicyError,
    evaluate_report,
    load_allowlist,
)
from scripts.terraform_demo_guard import (
    ActivePointer,
    GuardError,
    PlanManifest,
    verify_active_pointer_binding,
)
from scripts.verify_deployment_inputs import DeploymentInputError, verify_inputs


def _read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


def _workflow(root: Path, name: str) -> dict[str, Any]:
    value = yaml.load(_read(root, f".github/workflows/{name}"), Loader=yaml.BaseLoader)
    assert isinstance(value, dict)
    return value


def _oidc_subject(
    *,
    repository: str,
    owner_id: str,
    repository_id: str,
    ref: str,
    environment: str,
    workflow_path: str,
    immutable: bool,
) -> str:
    owner, name = repository.split("/", maxsplit=1)
    repository_subject = (
        f"repo:{owner}@{owner_id}/{name}@{repository_id}" if immutable else f"repo:{repository}"
    )
    return ":".join(
        (
            repository_subject,
            "ref",
            ref,
            "environment",
            environment,
            "workflow_ref",
            f"{repository}/{workflow_path}@{ref}",
        )
    )


def _terraform_statement(source: str, sid: str) -> str:
    lines = source.splitlines(keepends=True)
    sid_pattern = re.compile(rf'^\s+sid\s+= "{re.escape(sid)}"\s*$')
    sid_index = next(
        (index for index, line in enumerate(lines) if sid_pattern.fullmatch(line.rstrip("\n"))),
        None,
    )
    assert sid_index is not None, sid
    start = sid_index
    while start >= 0 and lines[start].strip() != "statement {":
        start -= 1
    assert start >= 0, sid
    depth = 0
    for end in range(start, len(lines)):
        stripped = lines[end].strip()
        if stripped.endswith("{"):
            depth += 1
        elif stripped == "}":
            depth -= 1
            if depth == 0:
                return "".join(lines[start : end + 1])
    raise AssertionError(f"unterminated Terraform statement: {sid}")


def _render_kms_statement(statement: str, *, region: str = "us-east-1") -> str:
    return statement.replace("${var.aws_region}", region)


def _kms_conditions(statement: str) -> dict[str, tuple[str, str]]:
    condition_pattern = re.compile(
        r"condition \{\s+"
        r'test\s+= "([^"]+)"\s+'
        r'variable\s+= "([^"]+)"\s+'
        r"values\s+= ([^\n]+)\s+\}",
        flags=re.MULTILINE,
    )
    conditions: dict[str, tuple[str, str]] = {}
    for test, variable, values in condition_pattern.findall(statement):
        assert variable not in conditions
        conditions[variable] = (test, values.strip())
    return conditions


def _assert_exact_notification_kms_statement(
    statement: str,
    *,
    principal: str,
    source_arns: str,
    region: str = "us-east-1",
) -> None:
    rendered = _render_kms_statement(statement, region=region)
    assert f'identifiers = ["{principal}"]' in rendered
    actions_match = re.search(r"actions = \[\s+(.*?)\s+\]", rendered, flags=re.DOTALL)
    assert actions_match is not None
    assert re.findall(r'"([^"]+)"', actions_match.group(1)) == [
        "kms:Decrypt",
        "kms:GenerateDataKey*",
    ]
    conditions = _kms_conditions(rendered)
    assert conditions == {
        "AWS:SourceAccount": ("StringEquals", "[var.aws_account_id]"),
        "AWS:SourceArn": ("StringEquals", source_arns),
        "kms:EncryptionContext:aws:sns:topicArn": (
            "StringEquals",
            "[local.alert_topic_arn]",
        ),
        "kms:ViaService": (
            "StringEquals",
            f'["sns.{region}.amazonaws.com"]',
        ),
    }
    assert all("*" not in values for _, values in conditions.values())


def _without_kms_condition(statement: str, variable: str) -> str:
    condition_pattern = re.compile(
        r"\n    condition \{\n"
        r'      test\s+= "[^"]+"\n'
        rf'      variable\s+= "{re.escape(variable)}"\n'
        r"      values\s+= [^\n]+\n"
        r"    \}\n"
    )
    mutated, replacements = condition_pattern.subn("\n", statement, count=1)
    assert replacements == 1, variable
    return mutated


def _replace_kms_condition_value(statement: str, variable: str, replacement: str) -> str:
    condition_pattern = re.compile(
        r"(?P<prefix>condition \{\s+"
        r'test\s+= "[^"]+"\s+'
        rf'variable\s+= "{re.escape(variable)}"\s+'
        r"values\s+= )[^\n]+",
        flags=re.MULTILINE,
    )
    mutated, replacements = condition_pattern.subn(
        lambda match: f"{match.group('prefix')}{replacement}",
        statement,
        count=1,
    )
    assert replacements == 1, variable
    assert mutated != statement
    return mutated


def _write_fake_curl(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """#!/usr/bin/env python3
import hashlib
import json
import os
import sys
from pathlib import Path

capture_dir = Path(os.environ["FAKE_CURL_CAPTURE_DIR"])
capture_dir.mkdir(parents=True, exist_ok=True)
argv = sys.argv[1:]
stdin_payload = sys.stdin.read() if "--config" in argv else ""
authorization_lines = [
    line
    for line in stdin_payload.splitlines()
    if line.startswith('header = "Authorization: Bearer ') and line.endswith('"')
]
authorization_token = (
    authorization_lines[0].removeprefix('header = "Authorization: Bearer ').removesuffix('"')
    if len(authorization_lines) == 1
    else ""
)
record = {
    "argv": argv,
    "environment_keys": sorted(os.environ),
    "prediction_token_environment_present": "PREDICTION_BEARER_TOKEN" in os.environ,
    "token_in_argv": bool(authorization_token) and any(
        authorization_token in argument for argument in argv
    ),
    "token_in_environment": bool(authorization_token) and any(
        authorization_token in value for value in os.environ.values()
    ),
    "stdin_authorization_lines": len(authorization_lines),
    "stdin_authorization_token_sha256": (
        hashlib.sha256(authorization_token.encode("utf-8")).hexdigest()
        if authorization_token
        else None
    ),
    "stdin_sha256": hashlib.sha256(stdin_payload.encode("utf-8")).hexdigest(),
}
index = len(list(capture_dir.glob("call-*.json")))
(capture_dir / f"call-{index:02d}.json").write_text(
    json.dumps(record, indent=2, sort_keys=True) + "\\n", encoding="utf-8"
)
url = next(
    (argument for argument in reversed(argv) if argument.startswith(("http://", "https://"))),
    "",
)
if os.environ.get("FAKE_CURL_HTTP_FAILURE") == "true" and url.endswith("/v1/predict"):
    print("simulated HTTP failure", file=sys.stderr)
    raise SystemExit(22)
if url.endswith("/health/live"):
    response = {"status": "live"}
elif url.endswith("/health/ready"):
    response = {"status": "ready"}
elif url.endswith("/version"):
    response = {
        "manifest_sha256": "a" * 64,
        "model_ready": True,
        "model_version": "1.0.0",
        "service_version": "test",
    }
elif url.endswith("/v1/predict"):
    response = {
        "decision": "low_risk",
        "latency_ms": 1.0,
        "model_version": (
            "2.0.0" if os.environ.get("FAKE_CURL_BAD_PREDICTION") == "true" else "1.0.0"
        ),
        "request_id": "00000000-0000-0000-0000-000000000001",
        "risk_score": 0.01,
    }
else:
    print("unexpected fake curl URL", file=sys.stderr)
    raise SystemExit(2)
sys.stdout.write(json.dumps(response))
""",
        encoding="utf-8",
    )
    path.chmod(0o700)


def _smoke_environment(
    *,
    repository_root: Path,
    temporary_root: Path,
    token: str,
    overrides: dict[str, str] | None = None,
) -> tuple[dict[str, str], Path, Path]:
    fake_curl = temporary_root / "bin" / "curl"
    _write_fake_curl(fake_curl)
    evidence = temporary_root / "evidence"
    captures = temporary_root / "captures"
    environment = os.environ.copy()
    environment.update(
        {
            "API_ACCESS_MODE": "https_token",
            "EVIDENCE_DIR": str(evidence),
            "EXPECTED_MODEL_MANIFEST_SHA256": "a" * 64,
            "EXPECTED_MODEL_VERSION": "1.0.0",
            "FAKE_CURL_CAPTURE_DIR": str(captures),
            "PATH": f"{fake_curl.parent}:{environment['PATH']}",
            "PREDICTION_BEARER_TOKEN": token,
            "SMOKE_BASE_URL": "https://demo.example.test",
            "UV_CACHE_DIR": str(repository_root / ".cache" / "uv"),
        }
    )
    environment.update(overrides or {})
    return environment, evidence, captures


def _assert_literal_absent_from_result_and_tree(
    *,
    literal: str,
    result: subprocess.CompletedProcess[str],
    root: Path,
) -> None:
    encoded = literal.encode("utf-8")
    if literal in result.stdout or literal in result.stderr:
        raise AssertionError("synthetic bearer token leaked to smoke command output")
    for path in root.rglob("*"):
        if path.is_file() and encoded in path.read_bytes():
            raise AssertionError("synthetic bearer token leaked to a smoke-test file")


class _FakeSts:
    def __init__(self, account_id: str = "123456789012") -> None:
        self.account_id = account_id

    def get_caller_identity(self) -> dict[str, Any]:
        return {"Account": self.account_id}


class _FakeSns:
    def __init__(self) -> None:
        self.subscriptions: list[dict[str, Any]] = []

    def list_subscriptions_by_topic(self, **kwargs: Any) -> dict[str, Any]:
        return {"Subscriptions": self.subscriptions}

    def subscribe(self, **kwargs: Any) -> dict[str, Any]:
        self.subscriptions.append(
            {
                "Endpoint": kwargs["Endpoint"],
                "Protocol": kwargs["Protocol"],
                "SubscriptionArn": "PendingConfirmation",
                "TopicArn": kwargs["TopicArn"],
            }
        )
        return {"SubscriptionArn": "PendingConfirmation"}


def _pointer() -> dict[str, Any]:
    names = {
        "baseline_profile.json",
        "checksums.sha256",
        "input_schema.json",
        "manifest.json",
        "metrics.json",
        "model.joblib",
        "threshold.json",
    }
    return {
        "pointer_schema_version": "modelguard.active-monitor-target.v1",
        "target_identity": {
            "event_schema_version": "modelguard.prediction-event.v1",
            "model_version": "1.0.0",
            "bundle_manifest_sha256": "a" * 64,
            "input_schema_version": "modelguard.input.v1",
        },
        "bundle": {
            "bucket": "modelguard-ai-demo-123456789012-us-east-1-models",
            "key_prefix": "model-bundles/1.0.0/",
            "object_version_ids": {name: f"version-{name}" for name in names},
        },
    }


def _plan_manifest() -> PlanManifest:
    return PlanManifest(
        stage="prerequisites",
        plan_filename="prerequisites.tfplan",
        plan_sha256="1" * 64,
        variable_file_sha256="2" * 64,
        backend_config_sha256="3" * 64,
        account_id="123456789012",
        region="us-east-1",
        project="modelguard-ai",
        environment="demo",
        backend_bucket="modelguard-ai-terraform-state-123456789012-us-east-1",
        backend_key="modelguard-ai/demo/terraform.tfstate",
        workspace="default",
        git_commit="4" * 40,
        activate_services=False,
        auto_destroy_date=date.today() + timedelta(days=7),
        sealed_at=datetime.now(tz=UTC),
    )


def test_required_workflows_parse_and_external_actions_are_commit_pinned(
    repository_root: Path,
) -> None:
    required = {
        "ci.yml",
        "container-security.yml",
        "terraform-plan.yml",
        "publish-images.yml",
        "deploy-demo.yml",
    }
    workflow_root = repository_root / ".github/workflows"
    assert required <= {path.name for path in workflow_root.glob("*.yml")}
    for name in required:
        workflow = _workflow(repository_root, name)
        assert "on" in workflow and isinstance(workflow.get("jobs"), dict)
        text = _read(repository_root, f".github/workflows/{name}")
        external_uses = re.findall(r"^\s*uses:\s*([^\s#]+)", text, flags=re.MULTILINE)
        assert external_uses
        for action in external_uses:
            if action.startswith("./"):
                continue
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action), action
    ci = _read(repository_root, ".github/workflows/ci.yml")
    security_scan = _read(repository_root, "scripts/security_scan.sh")
    assert "fetch-depth: 0" in ci
    assert "--redact=100" in security_scan
    assert "make security-tools-bootstrap" in ci
    assert "make security-scan" in ci
    assert "security-tools.lock.json" in _read(repository_root, "scripts/security_tools.py")
    assert "yamllint==1.37.1" in ci
    assert "UV_FROZEN" not in ci
    assert "uv sync --all-groups --locked" in ci
    assert "continue-on-error" not in ci
    assert "github/codeql-action/upload-sarif@" in ci


def test_untrusted_workflows_have_no_oidc_or_aws_and_plan_never_applies(
    repository_root: Path,
) -> None:
    ci = _read(repository_root, ".github/workflows/ci.yml")
    containers = _read(repository_root, ".github/workflows/container-security.yml")
    terraform = _read(repository_root, ".github/workflows/terraform-plan.yml")
    deploy = _read(repository_root, ".github/workflows/deploy-demo.yml")
    apply_script = _read(repository_root, "scripts/ci_apply_saved_plan.sh")
    for untrusted in (ci, containers):
        assert "id-token: write" not in untrusted
        assert "configure-aws-credentials" not in untrusted
        assert "AWS_ACCESS_KEY_ID" not in untrusted
        assert "AWS_SECRET_ACCESS_KEY" not in untrusted
    assert "github.ref == 'refs/heads/main'" in terraform
    assert "id-token: write" in terraform
    assert "terraform apply" not in terraform
    assert "pull_request" in terraform
    assert "terraform -target" not in terraform + deploy
    assert (
        "workflow_dispatch" in deploy and "pull_request" not in deploy.split("permissions:", 1)[0]
    )
    assert "environment: demo" in deploy
    assert 'test "$REPOSITORY_IS_PRIVATE" = "true"' in deploy
    assert "retention-days: 1" in deploy
    assert "prerequisites" in deploy and "activation" in deploy
    verify_job = deploy.split("  verify-inputs:", maxsplit=1)[1].split(
        "  activation-plan:", maxsplit=1
    )[0]
    assert verify_job.index("Verify the release manifest and digest outputs") < verify_job.index(
        "Assume the protected-environment deploy role through OIDC"
    )
    assert verify_job.index("aws ecr get-login-password") < verify_job.index("docker pull")
    assert "End the ECR verification session" in verify_job
    assert "raw Terraform output was suppressed" in apply_script
    assert '"$PLAN_FILE" >/dev/null 2>&1' in apply_script
    assert "verify-active-pointer" in apply_script


def test_oidc_subjects_and_workflow_permissions_are_exact(repository_root: Path) -> None:
    bootstrap = _read(repository_root, "infrastructure/bootstrap/iam.tf")
    variables = _read(repository_root, "infrastructure/bootstrap/variables.tf")
    template = json.loads(_read(repository_root, ".github/oidc-subject-template.json"))
    assert template == {
        "include_claim_keys": ["repo", "ref", "environment", "workflow_ref"],
        "use_default": False,
        "use_immutable_subject": True,
    }
    assert "github_oidc_use_immutable_subject" in bootstrap
    assert "github_repository_owner_id" in bootstrap
    assert "github_repository_id" in bootstrap
    for exact_value in (
        "refs/heads/main",
        "demo-plan",
        "demo",
        "demo-destroy",
        ".github/workflows/terraform-plan.yml",
        ".github/workflows/deploy-demo.yml",
        ".github/workflows/publish-images.yml",
        ".github/workflows/destroy-demo.yml",
    ):
        assert f'== "{exact_value}"' in variables
    plan_trust = bootstrap.split('data "aws_iam_policy_document" "github_plan_trust"', maxsplit=1)[
        1
    ].split('data "aws_iam_policy_document" "github_deploy_trust"', maxsplit=1)[0]
    deploy_trust = bootstrap.split(
        'data "aws_iam_policy_document" "github_deploy_trust"', maxsplit=1
    )[1].split('resource "aws_iam_role" "ci_plan"', maxsplit=1)[0]
    for trust in (plan_trust, deploy_trust):
        assert trust.count('test     = "StringEquals"') == 2
        assert "StringLike" not in trust
        assert "*" not in trust
        assert 'variable = "token.actions.githubusercontent.com:aud"' in trust
        assert 'variable = "token.actions.githubusercontent.com:sub"' in trust
    assert "repo:*" not in bootstrap

    repository = "octo-org/modelguard-ai"
    common_subject_arguments: dict[str, Any] = {
        "repository": repository,
        "owner_id": "123456",
        "repository_id": "987654",
        "ref": "refs/heads/main",
    }
    subject_specs = {
        "plan": ("demo-plan", ".github/workflows/terraform-plan.yml"),
        "deploy": ("demo", ".github/workflows/deploy-demo.yml"),
        "publish": ("demo", ".github/workflows/publish-images.yml"),
        "destroy": ("demo-destroy", ".github/workflows/destroy-demo.yml"),
    }
    expected_subjects = {
        name: _oidc_subject(
            **common_subject_arguments,
            environment=environment,
            workflow_path=workflow_path,
            immutable=True,
        )
        for name, (environment, workflow_path) in subject_specs.items()
    }
    legacy_subject = _oidc_subject(
        **common_subject_arguments,
        environment="demo-plan",
        workflow_path=".github/workflows/terraform-plan.yml",
        immutable=False,
    )
    immutable_subject = expected_subjects["plan"]
    assert legacy_subject == (
        "repo:octo-org/modelguard-ai:ref:refs/heads/main:environment:demo-plan:"
        "workflow_ref:octo-org/modelguard-ai/.github/workflows/terraform-plan.yml@refs/heads/main"
    )
    assert immutable_subject == (
        "repo:octo-org@123456/modelguard-ai@987654:ref:refs/heads/main:environment:demo-plan:"
        "workflow_ref:octo-org/modelguard-ai/.github/workflows/terraform-plan.yml@refs/heads/main"
    )
    exact_audience = "sts.amazonaws.com"

    def accepted(role: str, subject: str, audience: str) -> bool:
        allowed = (
            {expected_subjects["plan"]}
            if role == "plan"
            else {
                expected_subjects["deploy"],
                expected_subjects["publish"],
                expected_subjects["destroy"],
            }
        )
        return subject in allowed and audience == exact_audience

    assert accepted("plan", immutable_subject, exact_audience)
    for subject_name, subject in expected_subjects.items():
        role = "plan" if subject_name == "plan" else "deploy"
        assert accepted(role, subject, exact_audience)
        environment, workflow_path = subject_specs[subject_name]
        subject_arguments = {
            **common_subject_arguments,
            "environment": environment,
            "workflow_path": workflow_path,
        }
        mutations = (
            {**subject_arguments, "repository": "other-org/modelguard-ai"},
            {**subject_arguments, "owner_id": "654321"},
            {**subject_arguments, "repository_id": "456789"},
            {**subject_arguments, "ref": "refs/heads/release"},
            {**subject_arguments, "environment": "other-environment"},
            {**subject_arguments, "workflow_path": ".github/workflows/other.yml"},
        )
        for mutation in mutations:
            assert not accepted(role, _oidc_subject(**mutation, immutable=True), exact_audience)
        assert not accepted(role, subject, "https://github.com/octo-org")

    terraform = _workflow(repository_root, "terraform-plan.yml")
    assert terraform["jobs"]["trusted-prerequisite-plan"]["environment"] == "demo-plan"
    for workflow_name in ("terraform-plan.yml", "publish-images.yml", "deploy-demo.yml"):
        workflow = _workflow(repository_root, workflow_name)
        for job in workflow["jobs"].values():
            if not isinstance(job, dict) or job.get("permissions", {}).get("id-token") != "write":
                continue
            if "uses" in job:
                assert job["uses"] == "./.github/workflows/publish-images.yml"
                continue
            expected_environment = "demo-plan" if workflow_name == "terraform-plan.yml" else "demo"
            assert job.get("environment") == expected_environment
    publish = _read(repository_root, ".github/workflows/publish-images.yml")
    assert "environment: demo" in publish
    assert "id-token: write" in publish
    assert "aws-access-key-id" not in publish.casefold()
    assert "mask-aws-account-id: false" not in publish
    assert "mask-aws-account-id: true" in publish

    for workflow_name in ("terraform-plan.yml", "deploy-demo.yml"):
        workflow = _workflow(repository_root, workflow_name)
        for job in workflow["jobs"].values():
            assert isinstance(job, dict)
            job_environment = job.get("env", {})
            assert not any(key.startswith("TF_VAR_") for key in job_environment)
            assert "PREDICTION_BEARER_TOKEN" not in job_environment
    for workflow_name in ("terraform-plan.yml", "publish-images.yml", "deploy-demo.yml"):
        text = _read(repository_root, f".github/workflows/{workflow_name}")
        credential_steps = text.count("aws-actions/configure-aws-credentials@")
        assert credential_steps == text.count("allowed-account-ids:")
        assert credential_steps == text.count("audience: sts.amazonaws.com")


def test_release_build_scan_push_and_digest_promotion_order_is_fail_closed(
    repository_root: Path,
) -> None:
    publish = _read(repository_root, ".github/workflows/publish-images.yml")
    container_security = _read(repository_root, ".github/workflows/container-security.yml")
    assert container_security.count('".streamlit/**"') == 2
    assert publish.index("Refuse any release stage") < publish.index(
        "Assume the protected-environment deploy role through OIDC"
    )
    assert publish.index("Build all three release images exactly once") < publish.index(
        "Scan each exact content-addressed image"
    )
    assert "continue-on-error" not in publish
    assert publish.index("Scan each exact content-addressed image") < publish.index(
        "Assume the protected-environment deploy role through OIDC"
    )
    assert publish.index(
        "Assume the protected-environment deploy role through OIDC"
    ) < publish.index("Authenticate to ECR only after the image transfer is verified")
    assert publish.index(
        "Authenticate to ECR only after the image transfer is verified"
    ) < publish.index("Tag and push each already-scanned image")
    assert "git-${{ inputs.source_commit }}" in publish
    assert "@sha256:" in _read(repository_root, "scripts/verify_release_runtime.sh")
    assert "latest" not in "\n".join(
        line for line in publish.splitlines() if "docker push" in line or "image_ref=" in line
    )
    verify_release_source(repository_root)
    for component in ("api", "dashboard", "monitor"):
        dockerfile = _read(repository_root, f"docker/{component}.Dockerfile")
        assert re.search(r"^ARG PYTHON_BASE_IMAGE=.+@sha256:[0-9a-f]{64}$", dockerfile, re.M)


def test_release_manifest_uses_fresh_sanitized_remote_tag_inspection(
    repository_root: Path,
) -> None:
    workflow = _workflow(repository_root, "publish-images.yml")
    publish_job = workflow["jobs"]["publish"]
    tag_step = next(
        step
        for step in publish_job["steps"]
        if step.get("name") == "Tag and push each already-scanned image without rebuilding"
    )
    tag_script = str(tag_step["run"])
    sanitized_projection = (
        "{Id,RepoTags,RepoDigests,Config:{User:.Config.User,Labels:.Config.Labels}}"
    )

    assert tag_script.index('docker tag "$local_ref" "$remote_ref"') < tag_script.index(
        'docker image inspect "$remote_ref"'
    )
    assert sanitized_projection in tag_script
    assert '>"artifacts/image-release/inspect-${component}.json"' in tag_script
    assert "docker build" not in tag_script
    assert "security_scan.sh" not in tag_script

    source = _read(repository_root, ".github/workflows/publish-images.yml")
    assert source.index('docker image inspect "$remote_ref"') < source.index(
        "python -m scripts.release_manifest create"
    )


def test_history_secret_policy_requires_exact_owned_unexpired_scope(tmp_path: Path) -> None:
    evaluation_date = datetime.now(tz=UTC).date()
    scope = {
        "fingerprint": f"{'a' * 40}:docs/example.md:generic-api-key:7",
        "path": "docs/example.md",
        "rule_id": "generic-api-key",
        "commit": "a" * 40,
        "rationale": "Synthetic documentation fixture with no operational credential.",
        "owner": "security-owner",
        "expires_at": (evaluation_date + timedelta(days=30)).isoformat(),
    }
    allowlist_path = tmp_path / "allowlist.json"
    allowlist_path.write_text(
        json.dumps({"schema_version": "modelguard.secret-scan-allowlist.v1", "entries": [scope]}),
        encoding="utf-8",
    )
    policy = load_allowlist(allowlist_path)
    finding = {
        "Fingerprint": scope["fingerprint"],
        "File": scope["path"],
        "RuleID": scope["rule_id"],
        "Commit": scope["commit"],
        "StartLine": 7,
        "Secret": "must-not-survive",
        "Match": "must-not-survive",
    }
    evidence, passed = evaluate_report([finding], policy, scanner_version="8.30.1")
    assert passed
    assert "must-not-survive" not in json.dumps(evidence)
    assert evidence["findings"][0]["status"] == "allowlisted"
    with pytest.raises(SecretScanPolicyError, match="fingerprint"):
        evaluate_report([{**finding, "StartLine": 8}], policy, scanner_version="8.30.1")

    allowlist_path.write_text(
        json.dumps(
            {
                "schema_version": "modelguard.secret-scan-allowlist.v1",
                "entries": [
                    {**scope, "expires_at": (evaluation_date - timedelta(days=1)).isoformat()}
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SecretScanPolicyError, match="expired"):
        load_allowlist(allowlist_path)
    allowlist_path.write_text(
        json.dumps(
            {
                "schema_version": "modelguard.secret-scan-allowlist.v1",
                "entries": [
                    {**scope, "expires_at": (evaluation_date + timedelta(days=91)).isoformat()}
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SecretScanPolicyError, match="exceeds_90_days"):
        load_allowlist(allowlist_path)
    with pytest.raises(ValidationError):
        SecretScanAllowlist.model_validate(
            {
                "schema_version": "modelguard.secret-scan-allowlist.v1",
                "entries": [{**scope, "owner": ""}],
            }
        )


def test_plan_summary_never_copies_before_after_or_sensitive_values() -> None:
    secret = "sensitive-value-that-must-not-appear"
    raw_plan = {
        "format_version": "1.2",
        "terraform_version": "1.10.5",
        "resource_changes": [
            {
                "address": "aws_budgets_budget.demo",
                "provider_name": "registry.terraform.io/hashicorp/aws",
                "type": "aws_budgets_budget",
                "change": {
                    "actions": ["update"],
                    "before": {"email": secret},
                    "after": {"email": secret},
                    "after_sensitive": {"email": True},
                },
            }
        ],
        "output_changes": {
            "example": {"actions": ["update"], "after": secret, "after_sensitive": True}
        },
        "configuration": {"root_module": {"secret": secret}},
    }
    summary = summarize_plan(
        raw_plan,
        _plan_manifest(),
        repository="owner/repository",
        run_id="123",
        run_attempt="1",
        workflow_ref="owner/repository/.github/workflows/deploy-demo.yml@refs/heads/main",
    )
    rendered = json.dumps(summary) + render_markdown(summary)
    assert secret not in rendered
    assert "before" not in summary["resource_changes"][0]
    assert summary["action_counts"] == {"update": 1}
    assert summary["identity"]["activate_services"] is False
    assert summary["identity"]["account_id_masked"] == "********9012"
    assert "123456789012" not in rendered
    assert "modelguard-ai-terraform-state-123456789012-us-east-1" not in rendered
    assert "backend_bucket" not in summary["identity"]
    assert "backend_key" not in summary["identity"]
    assert "AutoDestroyDate" in render_markdown(summary)


def test_ci_input_renderer_enforces_prerequisite_and_activation_barriers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbidden_address = "operator@example.test"
    monkeypatch.setenv("TF_VAR_budget_notification_email", forbidden_address)
    common: dict[str, Any] = {
        "output_dir": tmp_path / "prerequisite",
        "stage": "prerequisites",
        "account_id": "123456789012",
        "region": "us-east-1",
        "owner_tag": "portfolio-owner",
        "governance_mode": "team_protected",
        "auto_destroy_date": (date.today() + timedelta(days=7)).isoformat(),
        "backend_bucket": "modelguard-ai-terraform-state-123456789012-us-east-1",
        "backend_kms_key_arn": (
            "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000"
        ),
        "permission_boundary_arn": (
            "arn:aws:iam::123456789012:policy/modelguard-ai/bootstrap/"
            "modelguard-ai-workload-boundary"
        ),
        "alert_kms_key_arn": (
            "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000"
        ),
        "alb_allowed_cidr": "203.0.113.10/32",
        "access_mode": "http_cidr_only",
    }
    paths = render_inputs(**common)
    tfvars = json.loads(paths["tfvars"].read_text(encoding="utf-8"))
    assert tfvars["activate_services"] is False
    assert tfvars["deployment_governance_mode"] == "team_protected"
    assert tfvars["runtime_contract_verified"] is False
    assert not any(key.endswith("_image_ref") for key in tfvars)
    assert "expected_model_version" not in tfvars
    assert tfvars["alert_kms_key_arn"] == common["alert_kms_key_arn"]
    for path in paths.values():
        rendered = path.read_text(encoding="utf-8")
        assert forbidden_address not in rendered
        assert "notification_email" not in rendered

    registry = "123456789012.dkr.ecr.us-east-1.amazonaws.com/modelguard-ai/demo"
    image_refs = {
        "api": f"{registry}/api@sha256:{'1' * 64}",
        "dashboard": f"{registry}/dashboard@sha256:{'2' * 64}",
        "monitor": f"{registry}/monitor@sha256:{'3' * 64}",
    }
    activation = {
        **common,
        "output_dir": tmp_path / "activation",
        "stage": "activation",
        "image_refs": image_refs,
        "active_pointer": _pointer(),
        "budget_prerequisite_verified": True,
        "runtime_verification": {
            "contracts": {
                "api": "hydration-fail-closed",
                "dashboard": "typed-aws-health",
                "monitor": "one-shot-aws-run",
            },
            "images": image_refs,
            "mode": "immutable_digest",
            "schema_version": "modelguard.runtime-contract-verification.v2",
            "source_commit": "a" * 40,
            "source_revision": "a" * 40,
            "status": "passed",
            "uv_lock_sha256": hashlib.sha256(Path("uv.lock").read_bytes()).hexdigest(),
        },
        "source_commit": "a" * 40,
    }
    activation_paths = render_inputs(**activation)
    activation_tfvars = json.loads(activation_paths["tfvars"].read_text(encoding="utf-8"))
    assert activation_tfvars["activate_services"] is True
    assert activation_tfvars["budget_prerequisite_verified"] is True
    assert all(
        "@sha256:" in activation_tfvars[f"{name}_image_ref"] for name in activation["image_refs"]
    )
    assert activation_tfvars["expected_model_version"] == "1.0.0"
    assert activation_tfvars["expected_model_manifest_sha256"] == "a" * 64
    assert (
        activation_tfvars["expected_model_object_version_ids"]
        == _pointer()["bundle"]["object_version_ids"]
    )
    pointer_response = {
        "Parameter": {
            "Name": "/modelguard-ai/demo/models/active",
            "Type": "String",
            "Value": json.dumps(_pointer()),
        }
    }
    verify_active_pointer_binding(
        pointer_response=pointer_response,
        variable_file=activation_paths["tfvars"],
        account_id="123456789012",
        region="us-east-1",
    )
    changed_pointer = _pointer()
    changed_pointer["bundle"]["object_version_ids"]["manifest.json"] = "changed-version-id"
    with pytest.raises(GuardError, match="activation_binding_mismatch"):
        verify_active_pointer_binding(
            pointer_response={
                "Parameter": {
                    "Name": "/modelguard-ai/demo/models/active",
                    "Type": "String",
                    "Value": json.dumps(changed_pointer),
                }
            },
            variable_file=activation_paths["tfvars"],
            account_id="123456789012",
            region="us-east-1",
        )

    with pytest.raises((RenderInputError, ValidationError)):
        render_inputs(
            **{**activation, "image_refs": {"api": None, "dashboard": None, "monitor": None}}
        )
    with pytest.raises(RenderInputError, match="runtime_verification"):
        render_inputs(**{**activation, "runtime_verification": None})
    with pytest.raises(RenderInputError, match="source_commit"):
        render_inputs(**{**activation, "source_commit": "b" * 40})


def test_saved_plan_workflows_and_terraform_cannot_accept_notification_pii(
    repository_root: Path,
) -> None:
    for workflow_name in ("terraform-plan.yml", "deploy-demo.yml"):
        text = _read(repository_root, f".github/workflows/{workflow_name}")
        assert "TF_VAR_" not in text
        assert "DEMO_BUDGET_NOTIFICATION_EMAIL" not in text
        workflow = _workflow(repository_root, workflow_name)
        for job in workflow["jobs"].values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps", []):
                if not isinstance(step, dict):
                    continue
                if "actions/upload-artifact@" in step.get("uses", ""):
                    assert "secrets." not in json.dumps(step)

    terraform_root = repository_root / "infrastructure/environments/demo"
    terraform = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(terraform_root.glob("*.tf"))
    )
    example = _read(repository_root, "infrastructure/environments/demo/demo.auto.tfvars.example")
    assert "budget_notification_email" not in terraform + example
    assert "drift_notification_email" not in terraform + example
    assert "subscriber_email_addresses" not in terraform
    assert 'resource "aws_sns_topic_subscription"' not in terraform
    assert "ignore_changes = [notification]" not in terraform
    assert 'resource "aws_budgets_budget"' not in terraform
    assert 'check "manual_budget_prerequisite"' in terraform
    assert "budget_prerequisite_verified" in terraform
    assert "kms_master_key_id = var.alert_kms_key_arn" in terraform
    assert "alias/aws/sns" not in terraform
    assert 'resource "aws_sns_topic_policy" "alerts"' in terraform
    assert 'identifiers = ["budgets.amazonaws.com"]' in terraform
    assert 'identifiers = ["cloudwatch.amazonaws.com"]' in terraform
    assert 'sid       = "AllowExactBudgetNotification"' in terraform
    assert 'sid       = "AllowExactCloudWatchAlarmNotifications"' in terraform
    assert "AWS:SourceAccount" in terraform and "AWS:SourceArn" in terraform
    assert "values   = local.alert_alarm_arns" in terraform

    bootstrap = _read(repository_root, "infrastructure/bootstrap/main.tf")
    bootstrap_iam = _read(repository_root, "infrastructure/bootstrap/iam.tf")
    assert 'identifiers = ["budgets.amazonaws.com"]' in bootstrap
    assert 'identifiers = ["cloudwatch.amazonaws.com"]' in bootstrap
    assert 'sid    = "AllowExactBudgetEncryptedTopic"' in bootstrap
    assert 'sid    = "AllowExactCloudWatchAlarmsEncryptedTopic"' in bootstrap
    assert bootstrap.count('variable = "kms:EncryptionContext:aws:sns:topicArn"') == 2
    assert bootstrap.count('variable = "kms:ViaService"') == 2
    assert bootstrap.count('values   = ["sns.${var.aws_region}.amazonaws.com"]') == 2
    assert "values   = local.alarm_source_arns" in bootstrap
    assert "values   = [local.budget_source_arn]" in bootstrap
    assert 'sid    = "UseRetainedKeyForExactAlertTopic"' in bootstrap_iam
    assert "resources = [aws_kms_key.state.arn]" in bootstrap_iam
    assert 'variable = "kms:ViaService"' in bootstrap_iam

    for workflow_name in ("terraform-plan.yml", "deploy-demo.yml"):
        workflow_text = _read(repository_root, f".github/workflows/{workflow_name}")
        render_count = workflow_text.count("scripts.render_ci_terraform")
        assert render_count == workflow_text.count("--alert-kms-key-arn")
        assert render_count == workflow_text.count("TF_ALERT_KMS_KEY_ARN")

    deploy = _read(repository_root, ".github/workflows/deploy-demo.yml")
    assert deploy.index("notification-enrollment-gate:") < deploy.index("  publish-images:")
    assert "needs: notification-enrollment-gate" in deploy
    assert "scripts.notification_enrollment verify" in deploy


@pytest.mark.parametrize(
    ("sid", "principal", "source_arns"),
    [
        (
            "AllowExactBudgetEncryptedTopic",
            "budgets.amazonaws.com",
            "[local.budget_source_arn]",
        ),
        (
            "AllowExactCloudWatchAlarmsEncryptedTopic",
            "cloudwatch.amazonaws.com",
            "local.alarm_source_arns",
        ),
    ],
)
def test_notification_kms_statements_render_exact_regional_sns_viaservice(
    repository_root: Path,
    sid: str,
    principal: str,
    source_arns: str,
) -> None:
    bootstrap = _read(repository_root, "infrastructure/bootstrap/main.tf")
    statement = _terraform_statement(bootstrap, sid)
    _assert_exact_notification_kms_statement(
        statement,
        principal=principal,
        source_arns=source_arns,
    )


@pytest.mark.parametrize(
    ("sid", "principal", "source_arns"),
    [
        (
            "AllowExactBudgetEncryptedTopic",
            "budgets.amazonaws.com",
            "[local.budget_source_arn]",
        ),
        (
            "AllowExactCloudWatchAlarmsEncryptedTopic",
            "cloudwatch.amazonaws.com",
            "local.alarm_source_arns",
        ),
    ],
)
@pytest.mark.parametrize(
    "missing_condition",
    [
        "AWS:SourceAccount",
        "AWS:SourceArn",
        "kms:EncryptionContext:aws:sns:topicArn",
        "kms:ViaService",
    ],
)
def test_notification_kms_statements_reject_any_missing_security_condition(
    repository_root: Path,
    sid: str,
    principal: str,
    source_arns: str,
    missing_condition: str,
) -> None:
    bootstrap = _read(repository_root, "infrastructure/bootstrap/main.tf")
    statement = _without_kms_condition(
        _terraform_statement(bootstrap, sid),
        missing_condition,
    )
    with pytest.raises(AssertionError):
        _assert_exact_notification_kms_statement(
            statement,
            principal=principal,
            source_arns=source_arns,
        )


@pytest.mark.parametrize(
    ("sid", "principal", "source_arns"),
    [
        (
            "AllowExactBudgetEncryptedTopic",
            "budgets.amazonaws.com",
            "[local.budget_source_arn]",
        ),
        (
            "AllowExactCloudWatchAlarmsEncryptedTopic",
            "cloudwatch.amazonaws.com",
            "local.alarm_source_arns",
        ),
    ],
)
@pytest.mark.parametrize(
    "wrong_viaservice",
    ["sqs.us-east-1.amazonaws.com", "sns.us-west-2.amazonaws.com"],
)
def test_notification_kms_statements_reject_wrong_service_or_region(
    repository_root: Path,
    sid: str,
    principal: str,
    source_arns: str,
    wrong_viaservice: str,
) -> None:
    bootstrap = _read(repository_root, "infrastructure/bootstrap/main.tf")
    statement = _render_kms_statement(_terraform_statement(bootstrap, sid))
    statement = statement.replace("sns.us-east-1.amazonaws.com", wrong_viaservice)
    with pytest.raises(AssertionError):
        _assert_exact_notification_kms_statement(
            statement,
            principal=principal,
            source_arns=source_arns,
        )


@pytest.mark.parametrize(
    ("sid", "principal", "source_arns"),
    [
        (
            "AllowExactBudgetEncryptedTopic",
            "budgets.amazonaws.com",
            "[local.budget_source_arn]",
        ),
        (
            "AllowExactCloudWatchAlarmsEncryptedTopic",
            "cloudwatch.amazonaws.com",
            "local.alarm_source_arns",
        ),
    ],
)
def test_workload_viaservice_cannot_replace_key_policy_viaservice(
    repository_root: Path,
    sid: str,
    principal: str,
    source_arns: str,
) -> None:
    bootstrap = _read(repository_root, "infrastructure/bootstrap/main.tf")
    workload_iam = _read(repository_root, "infrastructure/bootstrap/iam.tf")
    assert 'variable = "kms:ViaService"' in workload_iam
    statement = _without_kms_condition(
        _terraform_statement(bootstrap, sid),
        "kms:ViaService",
    )
    with pytest.raises(AssertionError):
        _assert_exact_notification_kms_statement(
            statement,
            principal=principal,
            source_arns=source_arns,
        )


@pytest.mark.parametrize(
    ("sid", "principal", "source_arns", "variable", "wrong_value"),
    [
        pytest.param(
            "AllowExactBudgetEncryptedTopic",
            "budgets.amazonaws.com",
            "[local.budget_source_arn]",
            "AWS:SourceAccount",
            '["999999999999"]',
            id="budget-wrong-source-account",
        ),
        pytest.param(
            "AllowExactCloudWatchAlarmsEncryptedTopic",
            "cloudwatch.amazonaws.com",
            "local.alarm_source_arns",
            "AWS:SourceAccount",
            '["999999999999"]',
            id="cloudwatch-wrong-source-account",
        ),
        pytest.param(
            "AllowExactBudgetEncryptedTopic",
            "budgets.amazonaws.com",
            "[local.budget_source_arn]",
            "AWS:SourceArn",
            '["arn:aws:budgets::123456789012:budget/wrong-budget"]',
            id="budget-wrong-source-arn",
        ),
        pytest.param(
            "AllowExactCloudWatchAlarmsEncryptedTopic",
            "cloudwatch.amazonaws.com",
            "local.alarm_source_arns",
            "AWS:SourceArn",
            '["arn:aws:cloudwatch:us-east-1:123456789012:alarm:wrong-alarm"]',
            id="cloudwatch-wrong-source-arn",
        ),
        pytest.param(
            "AllowExactBudgetEncryptedTopic",
            "budgets.amazonaws.com",
            "[local.budget_source_arn]",
            "kms:EncryptionContext:aws:sns:topicArn",
            '["arn:aws:sns:us-east-1:123456789012:wrong-topic"]',
            id="budget-wrong-encryption-context",
        ),
        pytest.param(
            "AllowExactCloudWatchAlarmsEncryptedTopic",
            "cloudwatch.amazonaws.com",
            "local.alarm_source_arns",
            "kms:EncryptionContext:aws:sns:topicArn",
            '["arn:aws:sns:us-east-1:123456789012:wrong-topic"]',
            id="cloudwatch-wrong-encryption-context",
        ),
    ],
)
def test_notification_kms_statements_reject_wrong_condition_values(
    repository_root: Path,
    sid: str,
    principal: str,
    source_arns: str,
    variable: str,
    wrong_value: str,
) -> None:
    bootstrap = _read(repository_root, "infrastructure/bootstrap/main.tf")
    actual_statement = _terraform_statement(bootstrap, sid)
    mutated_statement = _replace_kms_condition_value(
        actual_statement,
        variable,
        wrong_value,
    )
    with pytest.raises(AssertionError):
        _assert_exact_notification_kms_statement(
            mutated_statement,
            principal=principal,
            source_arns=source_arns,
        )


def test_repository_never_expands_prediction_bearer_token_outside_hardened_reader(
    repository_root: Path,
) -> None:
    manifest_paths = _read(repository_root, "FILE_MANIFEST.txt").splitlines()
    token_expansion = re.compile(
        r"\$(?:PREDICTION_BEARER_TOKEN\b|\{PREDICTION_BEARER_TOKEN(?:[^}]*)\})"
    )
    matches: list[tuple[str, int, str]] = []
    for relative_path in [*manifest_paths, "FILE_MANIFEST.txt"]:
        path = repository_root / relative_path
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(source.splitlines(), start=1):
            if token_expansion.search(line):
                matches.append((relative_path, line_number, line.strip()))

    assert [path for path, _, _ in matches] == [
        "scripts/smoke_aws.sh",
        "scripts/smoke_aws.sh",
    ]
    assert matches[0][2].startswith('if [[ -z "')
    assert matches[1][2].startswith('bearer_token="')
    assert all("curl" not in line for _, _, line in matches)


def test_https_smoke_passes_bearer_only_through_anonymous_curl_config(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    token = "phase09." + "A" * 40 + "_safe"
    environment, evidence, captures = _smoke_environment(
        repository_root=repository_root,
        temporary_root=tmp_path,
        token=token,
    )
    result = subprocess.run(
        [str(repository_root / "scripts/smoke_aws.sh")],
        cwd=repository_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(captures.glob("call-*.json"))
    ]
    assert len(records) == 4
    for record in records:
        assert record["argv"][0] == "--disable"
        assert record["prediction_token_environment_present"] is False
        assert "PREDICTION_BEARER_TOKEN" not in record["environment_keys"]
        assert record["token_in_argv"] is False
        assert record["token_in_environment"] is False

    prediction = next(record for record in records if record["argv"][-1].endswith("/v1/predict"))
    assert prediction["argv"] == [
        "--disable",
        "--config",
        "-",
        "https://demo.example.test/v1/predict",
    ]
    assert prediction["stdin_authorization_lines"] == 1
    assert (
        prediction["stdin_authorization_token_sha256"]
        == hashlib.sha256(token.encode("utf-8")).hexdigest()
    )
    expected_config = "\n".join(
        (
            "fail",
            "silent",
            "show-error",
            "connect-timeout = 10",
            "max-time = 30",
            "retry = 0",
            'header = "Content-Type: application/json"',
            'data = "@examples/prediction-request.json"',
            f'header = "Authorization: Bearer {token}"',
            "",
        )
    )
    assert prediction["stdin_sha256"] == hashlib.sha256(expected_config.encode("utf-8")).hexdigest()
    assert all(
        record["stdin_authorization_lines"] == 0 for record in records if record is not prediction
    )
    assert (evidence / "summary.json").is_file()
    _assert_literal_absent_from_result_and_tree(literal=token, result=result, root=tmp_path)


def test_https_smoke_rejects_control_and_config_injection_before_curl(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    invalid_tokens = (
        "A" * 40 + "\nheader",
        "B" * 40 + "\rheader",
        "C" * 40 + '"',
        "D" * 40 + "\\",
        "E" * 40 + "=header",
    )
    for index, token in enumerate(invalid_tokens):
        case_root = tmp_path / f"invalid-{index}"
        environment, evidence, captures = _smoke_environment(
            repository_root=repository_root,
            temporary_root=case_root,
            token=token,
        )
        result = subprocess.run(
            [str(repository_root / "scripts/smoke_aws.sh")],
            cwd=repository_root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 2
        assert not evidence.exists()
        assert not captures.exists() or not any(captures.iterdir())
        _assert_literal_absent_from_result_and_tree(
            literal=token,
            result=result,
            root=case_root,
        )


def test_https_smoke_http_and_response_failures_remain_fail_closed(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    token = "phase09." + "B" * 40 + "_safe"
    for index, failure_variable in enumerate(
        ("FAKE_CURL_HTTP_FAILURE", "FAKE_CURL_BAD_PREDICTION")
    ):
        case_root = tmp_path / f"failure-{index}"
        environment, evidence, captures = _smoke_environment(
            repository_root=repository_root,
            temporary_root=case_root,
            token=token,
            overrides={failure_variable: "true"},
        )
        result = subprocess.run(
            [str(repository_root / "scripts/smoke_aws.sh")],
            cwd=repository_root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0
        assert not (evidence / "summary.json").exists()
        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(captures.glob("call-*.json"))
        ]
        prediction = next(
            record for record in records if record["argv"][-1].endswith("/v1/predict")
        )
        assert prediction["argv"][0] == "--disable"
        assert prediction["stdin_authorization_lines"] == 1
        assert prediction["token_in_argv"] is False
        assert prediction["token_in_environment"] is False
        _assert_literal_absent_from_result_and_tree(
            literal=token,
            result=result,
            root=case_root,
        )

    deploy_workflow = _workflow(repository_root, "deploy-demo.yml")
    smoke_steps = [
        step
        for step in deploy_workflow["jobs"]["post-deploy-smoke"]["steps"]
        if isinstance(step, dict) and step.get("run") == "./scripts/smoke_aws.sh"
    ]
    assert len(smoke_steps) == 2
    assert all("continue-on-error" not in step for step in smoke_steps)


def test_manual_notification_enrollment_is_value_free_and_idempotent() -> None:
    account_id = "123456789012"
    notification_email = "notification-owner@example.test"
    sts = _FakeSts(account_id)
    sns = _FakeSns()

    with pytest.raises(NotificationEnrollmentError, match="subscriber_count_invalid"):
        verify_notification_enrollment(
            account_id=account_id,
            region="us-east-1",
            sts_client=sts,
            sns_client=sns,
        )

    first = enroll_notifications(
        account_id=account_id,
        region="us-east-1",
        notification_email=notification_email,
        sts_client=sts,
        sns_client=sns,
    )
    assert first == {
        "notification_subscription": "confirmation_requested",
        "status": "passed",
    }
    assert notification_email not in json.dumps(first)
    assert sns.subscriptions[0]["Endpoint"] == notification_email
    assert sns.subscriptions[0]["SubscriptionArn"] == "PendingConfirmation"

    with pytest.raises(NotificationEnrollmentError, match="subscription_unconfirmed"):
        verify_notification_enrollment(
            account_id=account_id,
            region="us-east-1",
            sts_client=sts,
            sns_client=sns,
        )

    second = enroll_notifications(
        account_id=account_id,
        region="us-east-1",
        notification_email=notification_email,
        sts_client=sts,
        sns_client=sns,
    )
    assert second["notification_subscription"] == "pending_confirmation"
    sns.subscriptions[0]["SubscriptionArn"] = (
        "arn:aws:sns:us-east-1:123456789012:modelguard-ai-demo-alerts:"
        "00000000-0000-0000-0000-000000000000"
    )
    evidence = verify_notification_enrollment(
        account_id=account_id,
        region="us-east-1",
        sts_client=sts,
        sns_client=sns,
    )
    assert evidence == {"notification_subscribers_confirmed": 1, "status": "passed"}
    assert notification_email not in json.dumps(evidence)
    third = enroll_notifications(
        account_id=account_id,
        region="us-east-1",
        notification_email=notification_email,
        sts_client=sts,
        sns_client=sns,
    )
    assert third["notification_subscription"] == "unchanged_confirmed"

    with pytest.raises(NotificationEnrollmentError, match="subscriber_conflict"):
        enroll_notifications(
            account_id=account_id,
            region="us-east-1",
            notification_email="different-owner@example.test",
            sts_client=sts,
            sns_client=sns,
        )
    sns.subscriptions.append(
        {
            "Endpoint": "second-owner@example.test",
            "Protocol": "email",
            "SubscriptionArn": (
                "arn:aws:sns:us-east-1:123456789012:modelguard-ai-demo-alerts:"
                "11111111-1111-1111-1111-111111111111"
            ),
        }
    )
    with pytest.raises(NotificationEnrollmentError, match="subscriber_count_invalid"):
        verify_notification_enrollment(
            account_id=account_id,
            region="us-east-1",
            sts_client=sts,
            sns_client=sns,
        )
    with pytest.raises(NotificationEnrollmentError, match="aws_account_mismatch"):
        verify_notification_enrollment(
            account_id=account_id,
            region="us-east-1",
            sts_client=_FakeSts("999999999999"),
            sns_client=sns,
        )


def test_release_manifest_binds_scan_evidence_and_ecr_digest(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    evidence = tmp_path / "evidence"
    (repository / "docker").mkdir(parents=True)
    evidence.mkdir()
    (repository / "uv.lock").write_text("locked\n", encoding="utf-8")
    account = "123456789012"
    region = "us-east-1"
    commit = "a" * 40
    lock_sha = __import__("hashlib").sha256(b"locked\n").hexdigest()
    registry = f"{account}.dkr.ecr.{region}.amazonaws.com"
    for index, component in enumerate(("api", "dashboard", "monitor"), start=1):
        (repository / "docker" / f"{component}.Dockerfile").write_text(
            "ARG PYTHON_BASE_IMAGE=python:3.12@sha256:"
            + "b" * 64
            + "\nFROM ${PYTHON_BASE_IMAGE} AS runtime\n",
            encoding="utf-8",
        )
        repository_name = f"{registry}/modelguard-ai/demo/{component}"
        tag = f"git-{commit}"
        (evidence / f"inspect-{component}.json").write_text(
            json.dumps(
                [
                    {
                        "Id": f"sha256:{index}" + "0" * 63,
                        "RepoTags": [f"{repository_name}:{tag}"],
                        "RepoDigests": [],
                        "Config": {
                            "User": "10001:10001",
                            "Labels": {
                                "org.opencontainers.image.revision": commit,
                                "io.modelguard.uv-lock.sha256": lock_sha,
                                "io.modelguard.component": component,
                            },
                        },
                    }
                ]
            ),
            encoding="utf-8",
        )
        (evidence / f"ecr-{component}.json").write_text(
            json.dumps(
                {
                    "imageDetails": [
                        {"imageDigest": f"sha256:{index}" + "1" * 63, "imageTags": [tag]}
                    ]
                }
            ),
            encoding="utf-8",
        )
        (evidence / f"{component}.cdx.json").write_text(
            json.dumps({"bomFormat": "CycloneDX", "vulnerabilities": []}), encoding="utf-8"
        )
    verify_release_source(repository)
    manifest = create_manifest(
        repository_root=repository,
        evidence_dir=evidence,
        account_id=account,
        region=region,
        source_commit=commit,
        now=datetime.now(tz=UTC),
    )
    verify_manifest(manifest, account_id=account, region=region, source_commit=commit)
    assert set(manifest.images) == {"api", "dashboard", "monitor"}
    assert all("@sha256:" in item.image_ref for item in manifest.images.values())
    vulnerable_manifest = manifest.model_dump(mode="json")
    vulnerable_manifest["images"]["api"]["high_or_critical_findings"] = 1
    with pytest.raises(ValidationError):
        ImageReleaseManifest.model_validate(vulnerable_manifest)
    with pytest.raises(ReleaseManifestError, match="source_commit"):
        verify_manifest(manifest, account_id=account, region=region, source_commit="c" * 40)
    ImageReleaseManifest.model_validate(manifest.model_dump(mode="json"))


def test_deployment_input_verifier_never_fetches_or_records_token_value() -> None:
    pointer_response = {
        "Parameter": {
            "Name": "/modelguard-ai/demo/models/active",
            "Type": "String",
            "Value": json.dumps(_pointer()),
        }
    }
    with pytest.raises(ValidationError, match="fields must be exact"):
        ActivePointer.model_validate(
            {**_pointer(), "target_identity": {**_pointer()["target_identity"], "extra": "no"}}
        )
    token_arn = (
        "arn:aws:ssm:us-east-1:123456789012:parameter/modelguard-ai/demo/secrets/prediction-token"
    )
    token_metadata = {
        "Parameters": [
            {
                "Name": "/modelguard-ai/demo/secrets/prediction-token",
                "Type": "SecureString",
                "KeyId": "alias/aws/ssm",
            }
        ]
    }
    certificate_arn = (
        "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
    )
    certificate = {
        "Certificate": {
            "CertificateArn": certificate_arn,
            "Status": "ISSUED",
            "DomainName": "demo.example.test",
            "SubjectAlternativeNames": ["demo.example.test"],
        }
    }
    _, summary = verify_inputs(
        pointer_response=pointer_response,
        account_id="123456789012",
        region="us-east-1",
        model_version="1.0.0",
        manifest_sha256="a" * 64,
        access_mode="https_token",
        smoke_base_url="https://demo.example.test",
        token_metadata=token_metadata,
        token_parameter_arn=token_arn,
        certificate_metadata=certificate,
        certificate_arn=certificate_arn,
    )
    assert summary["token"]["value_fetched"] is False
    assert "Value" not in json.dumps(summary)
    with pytest.raises(DeploymentInputError, match="hostname"):
        verify_inputs(
            pointer_response=pointer_response,
            account_id="123456789012",
            region="us-east-1",
            model_version="1.0.0",
            manifest_sha256="a" * 64,
            access_mode="https_token",
            smoke_base_url="https://other.example.test",
            token_metadata=token_metadata,
            token_parameter_arn=token_arn,
            certificate_metadata=certificate,
            certificate_arn=certificate_arn,
        )
    with pytest.raises(DeploymentInputError, match="smoke_base_url"):
        verify_inputs(
            pointer_response=pointer_response,
            account_id="123456789012",
            region="us-east-1",
            model_version="1.0.0",
            manifest_sha256="a" * 64,
            access_mode="https_token",
            smoke_base_url="https://demo.example.test?token=forbidden",
            token_metadata=token_metadata,
            token_parameter_arn=token_arn,
            certificate_metadata=certificate,
            certificate_arn=certificate_arn,
        )


def test_deployment_record_binds_smoke_model_plans_images_and_tasks(tmp_path: Path) -> None:
    account = "123456789012"
    region = "us-east-1"
    commit = "4" * 40
    registry = f"{account}.dkr.ecr.{region}.amazonaws.com/modelguard-ai/demo"
    images = {
        component: ImageRelease(
            component=component,
            repository=f"{registry}/{component}",
            provenance_tag=f"git-{commit}",
            digest=f"sha256:{index}" + "1" * 63,
            image_ref=f"{registry}/{component}@sha256:{index}" + "1" * 63,
            local_image_id=f"sha256:{index}" + "0" * 63,
            source_revision_label=commit,
            uv_lock_sha256_label="2" * 64,
            dockerfile_sha256="3" * 64,
            base_image="python:3.12@sha256:" + "5" * 64,
            cyclonedx_sha256="6" * 64,
            high_or_critical_findings=0,
        )
        for index, component in enumerate(("api", "dashboard", "monitor"), start=1)
    }
    release = ImageReleaseManifest(
        schema_version="modelguard.image-release.v1",
        source_commit=commit,
        aws_account_id=account,
        aws_region=region,
        uv_lock_sha256="2" * 64,
        built_once=True,
        scanned_before_push=True,
        created_at=datetime.now(tz=UTC),
        images=images,
    )
    prerequisite = _plan_manifest()
    activation = PlanManifest(
        **{
            **prerequisite.model_dump(),
            "stage": "activation",
            "plan_filename": "activation.tfplan",
            "plan_sha256": "7" * 64,
            "activate_services": True,
        }
    )
    payloads: dict[str, Any] = {
        "image-manifest.json": release.model_dump(mode="json"),
        "pointer.json": _pointer(),
        "live-pointer-response.json": {
            "Parameter": {
                "Name": "/modelguard-ai/demo/models/active",
                "Type": "String",
                "Value": json.dumps(_pointer()),
            }
        },
        "task-definitions.json": {
            component: (
                f"arn:aws:ecs:{region}:{account}:task-definition/"
                f"modelguard-ai-demo-{component}:{index}"
            )
            for index, component in enumerate(("api", "dashboard", "monitor"), start=1)
        },
        "deployed-images.json": {
            component: image.image_ref for component, image in release.images.items()
        },
        "prerequisite.json": prerequisite.model_dump(mode="json"),
        "activation.json": activation.model_dump(mode="json"),
        "smoke.json": {
            "schema_version": "modelguard.aws-smoke-evidence.v1",
            "status": "passed",
            "checks": ["live", "ready", "version", "prediction"],
            "model_version": "1.0.0",
            "model_manifest_sha256": "a" * 64,
        },
    }
    for name, payload in payloads.items():
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")
    record = create_record(
        image_manifest_path=tmp_path / "image-manifest.json",
        pointer_path=tmp_path / "pointer.json",
        live_pointer_response_path=tmp_path / "live-pointer-response.json",
        task_definitions_path=tmp_path / "task-definitions.json",
        deployed_images_path=tmp_path / "deployed-images.json",
        prerequisite_manifest_path=tmp_path / "prerequisite.json",
        activation_manifest_path=tmp_path / "activation.json",
        smoke_summary_path=tmp_path / "smoke.json",
        github_repository="owner/repository",
        github_run_id="123",
        github_run_attempt="1",
        governance_mode="team_protected",
        now=datetime.now(tz=UTC),
    )
    assert record.active_model_pointer.target_identity["model_version"] == "1.0.0"
    assert record.deployment_governance_mode == "team_protected"
    assert set(record.task_definitions) == {"api", "dashboard", "monitor"}
    wrong_bucket = record.model_dump(mode="json")
    wrong_bucket["active_model_pointer"]["bundle"]["bucket"] = "untrusted-model-bucket"
    with pytest.raises(ValidationError, match="model bucket"):
        DeploymentRecord.model_validate(wrong_bucket)
    wrong_mode = record.model_dump(mode="json")
    wrong_mode["deployment_governance_mode"] = "unbound"
    with pytest.raises(ValidationError, match="deployment_governance_mode"):
        DeploymentRecord.model_validate(wrong_mode)

    changed_live_pointer = _pointer()
    changed_live_pointer["bundle"]["object_version_ids"]["manifest.json"] = "new-version-id"
    changed_live_response = {
        "Parameter": {
            "Name": "/modelguard-ai/demo/models/active",
            "Type": "String",
            "Value": json.dumps(changed_live_pointer),
        }
    }
    (tmp_path / "live-pointer-response.json").write_text(
        json.dumps(changed_live_response), encoding="utf-8"
    )
    with pytest.raises(DeploymentRecordError, match="live_pointer_mismatch"):
        create_record(
            image_manifest_path=tmp_path / "image-manifest.json",
            pointer_path=tmp_path / "pointer.json",
            live_pointer_response_path=tmp_path / "live-pointer-response.json",
            task_definitions_path=tmp_path / "task-definitions.json",
            deployed_images_path=tmp_path / "deployed-images.json",
            prerequisite_manifest_path=tmp_path / "prerequisite.json",
            activation_manifest_path=tmp_path / "activation.json",
            smoke_summary_path=tmp_path / "smoke.json",
            github_repository="owner/repository",
            github_run_id="123",
            github_run_attempt="1",
            governance_mode="team_protected",
        )
    (tmp_path / "live-pointer-response.json").write_text(
        json.dumps(payloads["live-pointer-response.json"]), encoding="utf-8"
    )

    mismatched_images = {
        **payloads["deployed-images.json"],
        "api": f"{registry}/api@sha256:" + "9" * 64,
    }
    (tmp_path / "deployed-images.json").write_text(json.dumps(mismatched_images), encoding="utf-8")
    with pytest.raises(DeploymentRecordError, match="deployed_image_mismatch"):
        create_record(
            image_manifest_path=tmp_path / "image-manifest.json",
            pointer_path=tmp_path / "pointer.json",
            live_pointer_response_path=tmp_path / "live-pointer-response.json",
            task_definitions_path=tmp_path / "task-definitions.json",
            deployed_images_path=tmp_path / "deployed-images.json",
            prerequisite_manifest_path=tmp_path / "prerequisite.json",
            activation_manifest_path=tmp_path / "activation.json",
            smoke_summary_path=tmp_path / "smoke.json",
            github_repository="owner/repository",
            github_run_id="123",
            github_run_attempt="1",
            governance_mode="team_protected",
        )
    (tmp_path / "deployed-images.json").write_text(
        json.dumps(payloads["deployed-images.json"]), encoding="utf-8"
    )

    bad_smoke = {**payloads["smoke.json"], "model_version": "2.0.0"}
    (tmp_path / "smoke.json").write_text(json.dumps(bad_smoke), encoding="utf-8")
    with pytest.raises(DeploymentRecordError, match="smoke_model"):
        create_record(
            image_manifest_path=tmp_path / "image-manifest.json",
            pointer_path=tmp_path / "pointer.json",
            live_pointer_response_path=tmp_path / "live-pointer-response.json",
            task_definitions_path=tmp_path / "task-definitions.json",
            deployed_images_path=tmp_path / "deployed-images.json",
            prerequisite_manifest_path=tmp_path / "prerequisite.json",
            activation_manifest_path=tmp_path / "activation.json",
            smoke_summary_path=tmp_path / "smoke.json",
            github_repository="owner/repository",
            github_run_id="123",
            github_run_attempt="1",
            governance_mode="team_protected",
        )


def test_failed_smoke_has_explicit_ecs_rollback_and_separate_model_policy(
    repository_root: Path,
) -> None:
    deploy = _read(repository_root, ".github/workflows/deploy-demo.yml")
    record = _read(repository_root, "scripts/deployment_record.py")
    assert "rollback-on-failure" in deploy
    assert "needs.activation-apply.result == 'cancelled'" in deploy
    assert "needs.post-deploy-smoke.outputs.runtime_smoke_passed != 'true'" in deploy
    assert deploy.index("Upload deployment, smoke, and candidate-record evidence") < deploy.index(
        "Promote the durable record only after all evidence operations pass"
    )
    assert deploy.index(
        "Create the candidate independent ECS and model rollback record"
    ) < deploy.index("Mark the verified runtime result before evidence storage")
    assert deploy.index("Mark the verified runtime result before evidence storage") < deploy.index(
        "Upload deployment, smoke, and candidate-record evidence"
    )
    smoke_job = deploy.split("  post-deploy-smoke:", maxsplit=1)[1].split(
        "  rollback-on-failure:", maxsplit=1
    )[0]
    assert "deployments/plan-identities/" in smoke_job
    assert "prerequisites.tfplan.identity.json" in smoke_job
    assert "activation.tfplan.identity.json" in smoke_job
    assert "actions/download-artifact" not in "\n".join(
        line for line in smoke_job.splitlines() if "plan" in line.casefold()
    )
    assert smoke_job.count("PREDICTION_BEARER_TOKEN:") == 1
    assert "env.API_ACCESS_MODE == 'http_cidr_only'" in smoke_job
    assert deploy.count("aws ecs update-service") >= 2
    assert "aws scheduler update-schedule" in deploy
    assert "--query 'Target.EcsParameters.TaskDefinitionArn'" in deploy
    assert ".Target.EcsParameters.TaskDefinitionArn=$task" in deploy
    assert ".Target.Arn=$task" not in deploy
    assert "model_pointer_action" in deploy
    assert "deployments/last-known-good.json" in deploy
    assert "drift_triggers_rollback" in record
    assert "never automatic from drift" in record
