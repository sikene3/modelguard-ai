"""Phase 08 Terraform ownership, activation, IAM, telemetry, and teardown static gates."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from scripts.terraform_demo_guard import (
    GuardError,
    PlanManifest,
    PreflightContext,
    evaluate_post_destroy_inventory,
    seal_plan,
    validate_restricted_cidr,
    verify_plan,
)


def _read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


def _clean_test_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "source-repository"
    repository.mkdir()
    (repository / "tracked.txt").write_text("canonical\n", encoding="utf-8")
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=repository, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ModelGuard Tests",
            "-c",
            "user.email=modelguard-tests@example.invalid",
            "commit",
            "-m",
            "test: initialize clean source",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return repository


def _rendered_prerequisite_tfvars(
    auto_destroy_date: date, *, teardown_authorized: bool = False
) -> dict[str, Any]:
    return {
        "activate_services": False,
        "alert_kms_key_arn": (
            "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000"
        ),
        "alb_allowed_cidr": "203.0.113.10/32",
        "api_access_mode": "http_cidr_only",
        "auto_destroy_date": auto_destroy_date.isoformat(),
        "availability_zones": ["us-east-1a", "us-east-1b"],
        "aws_account_id": "123456789012",
        "aws_region": "us-east-1",
        "backend_bucket_name": "modelguard-ai-terraform-state-123456789012-us-east-1",
        "budget_prerequisite_verified": False,
        "deployment_governance_mode": "solo_portfolio",
        "deployment_stage": "prerequisites",
        "owner_tag": "modelguard-maintainers",
        "permission_boundary_arn": (
            "arn:aws:iam::123456789012:policy/modelguard-ai/bootstrap/"
            "modelguard-ai-workload-boundary"
        ),
        "runtime_contract_verified": False,
        "teardown_authorized": teardown_authorized,
    }


def _write_private_bytes(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _write_private_prerequisite_tfvars(
    path: Path, auto_destroy_date: date, *, teardown_authorized: bool = False
) -> None:
    _write_private_bytes(
        path,
        (
            json.dumps(
                _rendered_prerequisite_tfvars(
                    auto_destroy_date, teardown_authorized=teardown_authorized
                ),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8"),
    )


def _write_private_backend(path: Path) -> None:
    _write_private_bytes(
        path,
        (
            b'bucket = "modelguard-ai-terraform-state-123456789012-us-east-1"\n'
            b'key = "modelguard-ai/demo/terraform.tfstate"\n'
            b'region = "us-east-1"\n'
            b"encrypt = true\n"
            b'kms_key_id = "arn:aws:kms:us-east-1:123456789012:'
            b'key/00000000-0000-0000-0000-000000000000"\n'
            b"use_lockfile = true\n"
        ),
    )


def _pointer(bucket: str) -> dict[str, Any]:
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
            "bucket": bucket,
            "key_prefix": "model-bundles/1.0.0/",
            "object_version_ids": {name: f"version-{name}" for name in names},
        },
    }


def _preflight(*, activation: bool, today: date) -> dict[str, Any]:
    bucket = "modelguard-ai-demo-123456789012-us-east-1-models"
    registry = "123456789012.dkr.ecr.us-east-1.amazonaws.com/modelguard-ai/demo"
    return {
        "account_id": "123456789012",
        "region": "us-east-1",
        "project": "modelguard-ai",
        "environment": "demo",
        "deployment_governance_mode": "team_protected",
        "backend_bucket": "modelguard-ai-terraform-state-123456789012-us-east-1",
        "backend_key": "modelguard-ai/demo/terraform.tfstate",
        "backend_kms_key_arn": (
            "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000"
        ),
        "workspace": "default",
        "alert_kms_key_arn": (
            "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000"
        ),
        "stage": "activation" if activation else "prerequisites",
        "activate_services": activation,
        "teardown_authorized": False,
        "runtime_contract_verified": activation,
        "budget_prerequisite_verified": activation,
        "alb_allowed_cidr": "203.0.113.10/32",
        "access_mode": "https_token",
        "acm_certificate_arn": (
            "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
        ),
        "prediction_token_ssm_arn": (
            "arn:aws:ssm:us-east-1:123456789012:"
            "parameter/modelguard-ai/demo/secrets/prediction-token"
        ),
        "image_refs": (
            {
                component: f"{registry}/{component}@sha256:{index * 64}"
                for component, index in {"api": "1", "dashboard": "2", "monitor": "3"}.items()
            }
            if activation
            else {"api": None, "dashboard": None, "monitor": None}
        ),
        "active_pointer": _pointer(bucket) if activation else None,
        "model_bucket": bucket,
        "auto_destroy_date": (today + timedelta(days=7)).isoformat(),
    }


@pytest.mark.parametrize(
    "cidr",
    ["0.0.0.0/0", "::/0", "2001:db8::/64", "203.0.113.1/24", "not-a-cidr"],
)
def test_guard_refuses_world_ipv6_noncanonical_and_invalid_cidrs(cidr: str) -> None:
    with pytest.raises(GuardError):
        validate_restricted_cidr(cidr)
    assert validate_restricted_cidr("203.0.113.10/32") == "203.0.113.10/32"


def test_preflight_refuses_every_activation_barrier_and_token_value_field() -> None:
    today = datetime.now(tz=UTC).date()
    valid = _preflight(activation=True, today=today)
    assert PreflightContext.model_validate(valid).activate_services

    mutations: tuple[tuple[str, Any], ...] = (
        ("deployment_governance_mode", "unbound"),
        ("activate_services", False),
        ("teardown_authorized", True),
        ("runtime_contract_verified", False),
        ("alb_allowed_cidr", "0.0.0.0/0"),
        ("prediction_token_ssm_arn", "raw-token-bytes"),
        ("acm_certificate_arn", None),
        ("active_pointer", None),
        ("image_refs", {"api": None, "dashboard": None, "monitor": None}),
        ("backend_key", "other.tfstate"),
        ("backend_bucket", "other-state-bucket"),
        ("model_bucket", "other-model-bucket"),
        (
            "alert_kms_key_arn",
            "arn:aws:kms:eu-west-1:123456789012:key/00000000-0000-0000-0000-000000000000",
        ),
        (
            "backend_kms_key_arn",
            "arn:aws:kms:us-east-1:123456789012:key/11111111-1111-1111-1111-111111111111",
        ),
        (
            "acm_certificate_arn",
            "arn:aws:acm:eu-west-1:123456789012:certificate/00000000-0000-0000-0000-000000000000",
        ),
        (
            "prediction_token_ssm_arn",
            "arn:aws:ssm:us-east-1:999999999999:"
            "parameter/modelguard-ai/demo/secrets/prediction-token",
        ),
        (
            "image_refs",
            {
                **valid["image_refs"],
                "api": "123456789012.dkr.ecr.us-east-1.amazonaws.com/other/api@sha256:" + "1" * 64,
            },
        ),
    )
    for field, replacement in mutations:
        candidate = {**valid, field: replacement}
        with pytest.raises(ValidationError):
            PreflightContext.model_validate(candidate)

    with pytest.raises(ValidationError):
        PreflightContext.model_validate({**valid, "prediction_token_value": "forbidden"})


def test_expired_date_requires_exact_dormant_teardown_authorization() -> None:
    today = datetime.now(tz=UTC).date()
    destroy = {
        **_preflight(activation=False, today=today),
        "stage": "destroy",
        "teardown_authorized": True,
        "auto_destroy_date": (today - timedelta(days=30)).isoformat(),
    }
    context = PreflightContext.model_validate(destroy)
    assert context.teardown_authorized is True
    assert context.activate_services is False

    with pytest.raises(ValidationError, match="teardown authorization"):
        PreflightContext.model_validate({**destroy, "teardown_authorized": False})
    with pytest.raises(ValidationError, match="activation flag"):
        PreflightContext.model_validate({**destroy, "activate_services": True})
    with pytest.raises(ValidationError, match="runtime inputs"):
        PreflightContext.model_validate({**destroy, "runtime_contract_verified": True})


def test_saved_plan_manifest_binds_hash_identity_stage_and_expiry(
    tmp_path: Path,
) -> None:
    repository_root = _clean_test_repository(tmp_path)
    plan = tmp_path / "prerequisites.tfplan"
    variables = tmp_path / "demo.tfvars.json"
    backend = tmp_path / "backend.hcl"
    today = datetime.now(tz=UTC).date()
    expiry = today + timedelta(days=7)
    _write_private_bytes(plan, b"opaque-saved-plan")
    _write_private_prerequisite_tfvars(variables, expiry)
    _write_private_backend(backend)
    sealed_at = datetime.now(tz=UTC)
    manifest = seal_plan(
        plan_path=plan,
        variable_file=variables,
        backend_config=backend,
        stage="prerequisites",
        account_id="123456789012",
        region="us-east-1",
        auto_destroy_date=expiry,
        activate_services=False,
        repository=repository_root,
        now=sealed_at,
    )
    verify_plan(
        manifest,
        plan_path=plan,
        variable_file=variables,
        backend_config=backend,
        account_id="123456789012",
        region="us-east-1",
        stage="prerequisites",
        repository=repository_root,
        today=today,
        now=sealed_at + timedelta(minutes=1),
    )

    with pytest.raises(GuardError):
        verify_plan(
            manifest,
            plan_path=plan,
            variable_file=variables,
            backend_config=backend,
            account_id="999999999999",
            region="us-east-1",
            stage="prerequisites",
            repository=repository_root,
            today=today,
            now=sealed_at + timedelta(minutes=1),
        )
    with pytest.raises(GuardError):
        verify_plan(
            manifest,
            plan_path=plan,
            variable_file=variables,
            backend_config=backend,
            account_id="123456789012",
            region="eu-west-1",
            stage="prerequisites",
            repository=repository_root,
            today=today,
            now=sealed_at + timedelta(minutes=1),
        )
    with pytest.raises(GuardError, match="rendered_tfvars"):
        verify_plan(
            manifest,
            plan_path=plan,
            variable_file=variables,
            backend_config=backend,
            account_id="123456789012",
            region="us-east-1",
            stage="activation",
            repository=repository_root,
            today=today,
            now=sealed_at + timedelta(minutes=1),
        )
    wrong_commit = PlanManifest.model_validate({**manifest.model_dump(), "git_commit": "f" * 40})
    with pytest.raises(GuardError, match="git_commit"):
        verify_plan(
            wrong_commit,
            plan_path=plan,
            variable_file=variables,
            backend_config=backend,
            account_id="123456789012",
            region="us-east-1",
            stage="prerequisites",
            repository=repository_root,
            today=today,
            now=sealed_at + timedelta(minutes=1),
        )
    with pytest.raises(ValidationError, match="workspace"):
        PlanManifest.model_validate({**manifest.model_dump(), "workspace": "other"})

    changed_tfvars = _rendered_prerequisite_tfvars(expiry)
    changed_tfvars["owner_tag"] = "another-owner"
    _write_private_bytes(
        variables,
        (json.dumps(changed_tfvars, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    with pytest.raises(GuardError, match="variable_file_sha256"):
        verify_plan(
            manifest,
            plan_path=plan,
            variable_file=variables,
            backend_config=backend,
            account_id="123456789012",
            region="us-east-1",
            stage="prerequisites",
            repository=repository_root,
            today=today,
            now=sealed_at + timedelta(minutes=1),
        )
    _write_private_prerequisite_tfvars(variables, expiry)
    backend.write_text(
        backend.read_text(encoding="utf-8") + "# identity change\n", encoding="utf-8"
    )
    with pytest.raises(GuardError, match="backend_config_sha256"):
        verify_plan(
            manifest,
            plan_path=plan,
            variable_file=variables,
            backend_config=backend,
            account_id="123456789012",
            region="us-east-1",
            stage="prerequisites",
            repository=repository_root,
            today=today,
            now=sealed_at + timedelta(minutes=1),
        )
    backend.write_text(
        backend.read_text(encoding="utf-8").removesuffix("# identity change\n"),
        encoding="utf-8",
    )

    stale_manifest = PlanManifest.model_validate(
        {**manifest.model_dump(), "sealed_at": sealed_at - timedelta(hours=25)}
    )
    with pytest.raises(GuardError, match="saved_plan_expired"):
        verify_plan(
            stale_manifest,
            plan_path=plan,
            variable_file=variables,
            backend_config=backend,
            account_id="123456789012",
            region="us-east-1",
            stage="prerequisites",
            repository=repository_root,
            today=today,
            now=sealed_at,
        )

    future_manifest = PlanManifest.model_validate(
        {**manifest.model_dump(), "sealed_at": sealed_at + timedelta(minutes=6)}
    )
    with pytest.raises(GuardError, match="saved_plan_sealed_at_in_future"):
        verify_plan(
            future_manifest,
            plan_path=plan,
            variable_file=variables,
            backend_config=backend,
            account_id="123456789012",
            region="us-east-1",
            stage="prerequisites",
            repository=repository_root,
            today=today,
            now=sealed_at,
        )

    plan.write_bytes(b"tampered-plan")
    with pytest.raises(GuardError, match="plan_sha256"):
        verify_plan(
            manifest,
            plan_path=plan,
            variable_file=variables,
            backend_config=backend,
            account_id="123456789012",
            region="us-east-1",
            stage="prerequisites",
            repository=repository_root,
            today=today,
        )
    with pytest.raises(ValidationError):
        PlanManifest.model_validate({**manifest.model_dump(), "plan_filename": "ad-hoc.tfplan"})

    _write_private_bytes(plan, b"opaque-saved-plan")
    backend.write_text(
        backend.read_text(encoding="utf-8").replace(
            "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000",
            "arn:aws:kms:eu-west-1:123456789012:key/00000000-0000-0000-0000-000000000000",
        ),
        encoding="utf-8",
    )
    with pytest.raises(GuardError, match="backend_kms_key_identity_mismatch"):
        seal_plan(
            plan_path=plan,
            variable_file=variables,
            backend_config=backend,
            stage="prerequisites",
            account_id="123456789012",
            region="us-east-1",
            auto_destroy_date=expiry,
            activate_services=False,
            repository=repository_root,
        )


def test_expired_reminder_never_blocks_an_exact_destroy_plan(
    tmp_path: Path,
) -> None:
    repository_root = _clean_test_repository(tmp_path)
    plan = tmp_path / "destroy.tfplan"
    variables = tmp_path / "demo.tfvars.json"
    backend = tmp_path / "backend.hcl"
    today = datetime.now(tz=UTC).date()
    expiry = today - timedelta(days=1)
    _write_private_bytes(plan, b"opaque-destroy-plan")
    _write_private_prerequisite_tfvars(variables, expiry, teardown_authorized=True)
    _write_private_backend(backend)
    manifest = seal_plan(
        plan_path=plan,
        variable_file=variables,
        backend_config=backend,
        stage="destroy",
        account_id="123456789012",
        region="us-east-1",
        auto_destroy_date=expiry,
        activate_services=False,
        source_activation_state="active",
        repository=repository_root,
    )
    verify_plan(
        manifest,
        plan_path=plan,
        variable_file=variables,
        backend_config=backend,
        account_id="123456789012",
        region="us-east-1",
        stage="destroy",
        repository=repository_root,
        today=today,
    )


def test_activation_defaults_off_and_runtime_state_is_derived_only_from_barrier(
    repository_root: Path,
) -> None:
    variables = _read(repository_root, "infrastructure/environments/demo/variables.tf")
    locals = _read(repository_root, "infrastructure/environments/demo/locals.tf")
    scheduler = _read(repository_root, "infrastructure/environments/demo/scheduler.tf")
    ecs = _read(repository_root, "infrastructure/environments/demo/ecs.tf")

    activation_block = variables.split('variable "activate_services"', maxsplit=1)[1].split(
        "}\n", maxsplit=1
    )[0]
    assert "default     = false" in activation_block
    teardown_block = variables.split('variable "teardown_authorized"', maxsplit=1)[1].split(
        "}\n", maxsplit=1
    )[0]
    assert "default     = false" in teardown_block
    assert "var.teardown_authorized || try(" in locals
    assert "var.teardown_authorized &&" in locals
    assert "!var.runtime_contract_verified" in locals
    assert "!var.budget_prerequisite_verified" in locals
    assert "runtime_desired_count" in locals
    assert 'resource "terraform_data" "deployment_guard"' in locals
    assert locals.count("precondition {") >= 10
    assert "must exactly match monitor_schedule_expression" in locals
    assert "schedule_period_seconds" in locals
    assert "expected_bundle_filenames" in locals
    assert "var.activate_services ? 1 : 0" in locals
    assert 'monitor_schedule_state = var.activate_services ? "ENABLED" : "DISABLED"' in locals
    observability = _read(repository_root, "infrastructure/environments/demo/observability.tf")
    assert (
        "alarm_actions = var.activate_services ? [aws_sns_topic.alerts.arn] : []" in observability
    )
    assert ecs.count("desired_count") >= 2
    assert ecs.count("local.runtime_desired_count") == 2
    assert "state" in scheduler and "local.monitor_schedule_state" in scheduler
    assert "terraform-target" not in _read(
        repository_root, "docs/08_AWS_DEPLOYMENT_ORDER.md"
    ).replace("terraform -target", "")


def test_bootstrap_owns_exact_oidc_boundary_and_passrole_scope(repository_root: Path) -> None:
    bootstrap = _read(repository_root, "infrastructure/bootstrap/iam.tf")
    demo_iam = _read(repository_root, "infrastructure/environments/demo/iam.tf")

    assert 'variable = "token.actions.githubusercontent.com:aud"' in bootstrap
    assert 'values   = ["sts.amazonaws.com"]' in bootstrap
    assert "github_repository_owner_id" in bootstrap
    assert "github_repository_id" in bootstrap
    assert '"ref"' in bootstrap and "var.github_allowed_ref" in bootstrap
    assert '"environment"' in bootstrap and '"workflow_ref"' in bootstrap
    assert "var.github_plan_workflow_path" in bootstrap
    assert "var.github_deploy_workflow_path" in bootstrap
    assert "var.github_publish_workflow_path" in bootstrap
    assert "var.github_destroy_workflow_path" in bootstrap
    assert "token.actions.githubusercontent.com:sub" in bootstrap
    assert "repo:*" not in bootstrap
    assert '"iam:PassRole"' in bootstrap
    assert 'variable = "iam:PassedToService"' in bootstrap
    assert "local.workload_role_resources" in bootstrap
    assert "iam:PermissionsBoundary" in bootstrap
    assert "aws_iam_openid_connect_provider" not in demo_iam
    assert demo_iam.count("permissions_boundary = var.permission_boundary_arn") == 6
    assert "iam:CreatePolicy" not in bootstrap
    assert 'actions = ["*"]' not in bootstrap


def test_securestring_is_arn_only_and_injected_through_ecs_secrets(repository_root: Path) -> None:
    demo_root = repository_root / "infrastructure/environments/demo"
    terraform = "\n".join(path.read_text(encoding="utf-8") for path in demo_root.glob("*.tf"))
    example = _read(repository_root, "infrastructure/environments/demo/demo.auto.tfvars.example")
    outputs = _read(repository_root, "infrastructure/environments/demo/outputs.tf")

    assert 'variable "prediction_token_ssm_arn"' in terraform
    assert "parameter/modelguard-ai/demo/secrets/" in terraform
    assert 'name       = "PREDICTION_BEARER_TOKEN"' in terraform
    assert "value_from = var.prediction_token_ssm_arn" in terraform
    assert "PREDICTION_TOKEN_SSM_ARN" in terraform
    assert "PREDICTION_TOKEN_VALUE" not in terraform
    assert "prediction_token_value" not in terraform
    assert "WithDecryption" not in terraform
    assert "token bytes" in example
    assert "prediction_token_ssm_arn" not in outputs


def test_alarm_matrix_has_a_real_native_or_emf_source_and_correct_missing_policy(
    repository_root: Path,
) -> None:
    matrix = json.loads(_read(repository_root, "infrastructure/alarm-sources.json"))
    observability = _read(repository_root, "infrastructure/environments/demo/observability.tf")
    api_source = _read(repository_root, "src/modelguard/core/telemetry.py")
    monitor_source = _read(repository_root, "src/modelguard/monitoring/telemetry.py")

    assert matrix["schema_version"] == "modelguard.terraform-alarm-sources.v1"
    assert len(matrix["alarms"]) == 11
    assert len({alarm["key"] for alarm in matrix["alarms"]}) == 11
    for alarm in matrix["alarms"]:
        resource_type, resource_name = alarm["terraform_resource"].split(".")
        assert resource_type == "aws_cloudwatch_metric_alarm"
        assert f'resource "{resource_type}" "{resource_name}"' in observability
        assert f'metric_name         = "{alarm["metric"]}"' in observability
        assert f'namespace           = "{alarm["namespace"]}"' in observability
        assert f'treat_missing_data  = "{alarm["missing_data"]}"' in observability
        if alarm["source_kind"] == "emf":
            source = api_source if alarm["key"].startswith("api_") else monitor_source
            assert f'"{alarm["metric"]}"' in source
        else:
            assert alarm["namespace"].startswith("AWS/")
    monitor_alarms = [alarm for alarm in matrix["alarms"] if alarm["key"].startswith("monitor_")]
    assert {alarm["missing_data"] for alarm in monitor_alarms} == {"breaching"}
    api_failure = next(
        alarm for alarm in matrix["alarms"] if alarm["key"] == "api_event_write_failures"
    )
    assert api_failure["missing_data"] == "notBreaching"
    assert "scheduler submission" in observability.casefold()
    assert "ECS/ContainerInsights" not in observability


def _post_destroy_inventory() -> dict[str, Any]:
    service_categories = {
        "alarms",
        "ecs_clusters",
        "ecs_services",
        "ecs_task_definitions_active",
        "ecs_tasks",
        "ecr_images",
        "ecr_repositories",
        "eips",
        "firehose_streams",
        "internet_gateways",
        "listener_rules",
        "listeners",
        "load_balancers",
        "log_groups",
        "nat_gateways",
        "route_tables",
        "s3_buckets",
        "s3_multipart_uploads",
        "s3_object_versions",
        "scheduler_groups",
        "scheduler_schedules",
        "security_groups",
        "sns_subscriptions",
        "sns_topics",
        "ssm_pointers",
        "subnets",
        "target_groups",
        "vpc_endpoints",
        "vpcs",
        "workload_roles",
    }
    return {
        "schema_version": "modelguard.post-destroy-inventory.v2",
        "identity": {
            "account_id": "123456789012",
            "region": "us-east-1",
            "project": "modelguard-ai",
            "environment": "demo",
        },
        "ResourceTagMappingList": [],
        "service_residuals": {name: [] for name in service_categories},
        "retained_resources": {"budgets": ["modelguard-ai-demo-monthly"]},
        "nonbillable_metadata": {"ecs_task_definitions_inactive": []},
    }


def _evaluate_post_destroy_inventory(
    payload: dict[str, Any],
    *,
    account_id: str = "123456789012",
    region: str = "us-east-1",
) -> dict[str, list[str]]:
    return evaluate_post_destroy_inventory(
        payload,
        account_id=account_id,
        region=region,
    )


def _write_fake_aws(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
capture = Path(os.environ["FAKE_AWS_CAPTURE"])
with capture.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(arguments, separators=(",", ":")) + "\\n")
with Path(os.environ["FAKE_EXECUTION_CAPTURE"]).open("a", encoding="utf-8") as handle:
    handle.write("aws:" + " ".join(arguments) + "\\n")

position = 0
while position < len(arguments) and arguments[position] in {"--profile", "--region"}:
    position += 2
service = arguments[position] if position < len(arguments) else ""
operation = arguments[position + 1] if position + 1 < len(arguments) else ""

if service == os.environ.get("FAKE_AWS_FAIL_SERVICE"):
    sys.stdout.write(os.environ["FAKE_AWS_STDOUT_SENTINEL"])
    sys.stderr.write(os.environ["FAKE_AWS_STDERR_SENTINEL"])
    raise SystemExit(91)

if (service, operation) == ("sts", "get-caller-identity"):
    payload = {
        "Account": os.environ.get("FAKE_CALLER_ACCOUNT", os.environ["EXPECTED_AWS_ACCOUNT_ID"]),
        "Arn": os.environ["FAKE_CALLER_ARN"],
    }
elif (service, operation) == ("resourcegroupstaggingapi", "get-resources"):
    payload = {"ResourceTagMappingList": []}
elif (service, operation) == ("ecr", "describe-repositories"):
    payload = {"repositories": []}
elif (service, operation) == ("budgets", "describe-budgets"):
    payload = ["modelguard-ai-demo-monthly"]
elif (service, operation) == ("cloudwatch", "describe-alarms"):
    query = arguments[arguments.index("--query") + 1]
    if "MetricAlarms" not in query or "CompositeAlarms" not in query:
        raise SystemExit(93)
    composite_alarm = os.environ.get("FAKE_COMPOSITE_ALARM_ARN")
    payload = [composite_alarm] if composite_alarm else []
elif (service, operation) == ("s3api", "list-object-versions"):
    payload = {"Versions": [], "DeleteMarkers": []}
elif (service, operation) == ("s3api", "list-multipart-uploads"):
    payload = {"Uploads": []}
else:
    payload = []
sys.stdout.write(json.dumps(payload))
""",
        encoding="utf-8",
    )
    path.chmod(0o700)


def _write_fake_uv(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
human_prefix = [
    "run", "--frozen", "--no-sync", "python", "-m",
    "scripts.human_aws_login", "verify",
]
if arguments[:len(human_prefix)] == human_prefix:
    expected = human_prefix + [
        "--profile", "modelguard-bootstrap",
        "--region", "us-east-1",
        "--expected-account-id", os.environ["EXPECTED_AWS_ACCOUNT_ID"],
    ]
    with Path(os.environ["FAKE_HUMAN_LOGIN_CAPTURE"]).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(arguments, separators=(",", ":")) + "\\n")
    with Path(os.environ["FAKE_EXECUTION_CAPTURE"]).open("a", encoding="utf-8") as handle:
        handle.write("human-login\\n")
    credential_method = os.environ.get("FAKE_HUMAN_CREDENTIAL_METHOD", "login")
    environment_credentials = any(
        name in os.environ
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
    )
    if arguments != expected or credential_method != "login" or environment_credentials:
        raise SystemExit(92)
    raise SystemExit(0)

real_uv = os.environ["REAL_UV"]
os.execv(real_uv, [real_uv, *arguments])
""",
        encoding="utf-8",
    )
    path.chmod(0o700)


def _teardown_test_environment(
    *,
    repository_root: Path,
    tmp_path: Path,
    caller_arn: str,
) -> tuple[dict[str, str], Path, Path]:
    tmp_path.chmod(0o700)
    fake_aws = tmp_path / "bin" / "aws"
    fake_uv = tmp_path / "bin" / "uv"
    _write_fake_aws(fake_aws)
    _write_fake_uv(fake_uv)
    capture = tmp_path / "aws-calls.jsonl"
    execution_capture = tmp_path / "execution-order.log"
    human_login_capture = tmp_path / "human-login-calls.jsonl"
    inventory = tmp_path / "post-destroy-inventory.json"
    environment = os.environ.copy()
    real_uv = shutil.which("uv", path=environment.get("PATH"))
    assert real_uv is not None
    for name in (
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "EXPECTED_AWS_ROLE_ARN",
        "FAKE_AWS_FAIL_SERVICE",
        "FAKE_AWS_STDERR_SENTINEL",
        "FAKE_AWS_STDOUT_SENTINEL",
        "FAKE_HUMAN_CREDENTIAL_METHOD",
        "GITHUB_ACTIONS",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "AWS_REGION": "us-east-1",
            "EXPECTED_AWS_ACCOUNT_ID": "123456789012",
            "FAKE_AWS_CAPTURE": str(capture),
            "FAKE_CALLER_ARN": caller_arn,
            "FAKE_EXECUTION_CAPTURE": str(execution_capture),
            "FAKE_HUMAN_LOGIN_CAPTURE": str(human_login_capture),
            "INVENTORY_OUTPUT": str(inventory),
            "PATH": f"{fake_aws.parent}:{environment['PATH']}",
            "REAL_UV": real_uv,
            "UV_CACHE_DIR": str(repository_root / ".cache" / "uv"),
        }
    )
    return environment, capture, inventory


def _run_teardown_verifier(
    *, repository_root: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repository_root / "scripts/verify_aws_teardown.sh")],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _captured_aws_calls(path: Path) -> list[list[str]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _captured_human_login_calls(tmp_path: Path) -> list[list[str]]:
    path = tmp_path / "human-login-calls.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _assert_private_inventory_evidence(path: Path) -> None:
    assert path.parent.is_dir()
    assert not path.parent.is_symlink()
    assert path.parent.stat().st_uid == os.geteuid()
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert path.is_file()
    assert not path.is_symlink()
    assert path.stat().st_uid == os.geteuid()
    assert path.stat().st_mode & 0o777 == 0o600


def _assert_bounded_inventory_summary(
    completed: subprocess.CompletedProcess[str],
    *,
    status: str,
    residual_service_count: int = 0,
) -> dict[str, Any]:
    output = completed.stdout if status == "passed" else completed.stderr
    other_output = completed.stderr if status == "passed" else completed.stdout
    assert other_output == ""
    summary = json.loads(output)
    assert set(summary) == {
        "account_id_masked",
        "category_counts",
        "guard",
        "region",
        "status",
    } | ({"reason"} if status == "refused" else set())
    assert summary["account_id_masked"] == "********9012"
    assert summary["region"] == "us-east-1"
    assert summary["guard"] == "verify-inventory"
    assert summary["status"] == status
    assert summary["category_counts"] == {
        "residual_demo": 0,
        "residual_service": residual_service_count,
        "retained_bootstrap": 0,
        "retained_budget": 1 if status == "passed" or residual_service_count else 0,
        "validated_nonbillable": 0,
        "unrelated": 0,
    }
    combined_output = completed.stdout + completed.stderr
    assert "123456789012" not in combined_output
    assert "arn:aws:" not in combined_output
    return summary


def _run_inventory_guard(
    *,
    repository_root: Path,
    input_path: Path,
    account_id: str = "123456789012",
    region: str = "us-east-1",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(repository_root / "scripts/terraform_demo_guard.py"),
            "verify-inventory",
            "--input",
            str(input_path),
            "--account-id",
            account_id,
            "--region",
            region,
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )


def test_teardown_inventory_human_mode_propagates_exact_profile_and_region(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    account_id = "123456789012"
    environment, capture, inventory = _teardown_test_environment(
        repository_root=repository_root,
        tmp_path=tmp_path,
        caller_arn=f"arn:aws:iam::{account_id}:user/modelguard-bootstrap-admin",
    )
    environment["AWS_PROFILE"] = "modelguard-bootstrap"

    completed = _run_teardown_verifier(
        repository_root=repository_root,
        environment=environment,
    )

    assert completed.returncode == 0, completed.stderr
    calls = _captured_aws_calls(capture)
    assert len(calls) >= 20
    assert all(
        call[:4] == ["--region", "us-east-1", "--profile", "modelguard-bootstrap"] for call in calls
    )
    assert calls[0][4:6] == ["sts", "get-caller-identity"]
    assert _captured_human_login_calls(tmp_path) == [
        [
            "run",
            "--frozen",
            "--no-sync",
            "python",
            "-m",
            "scripts.human_aws_login",
            "verify",
            "--profile",
            "modelguard-bootstrap",
            "--region",
            "us-east-1",
            "--expected-account-id",
            account_id,
        ]
    ]
    execution_order = (tmp_path / "execution-order.log").read_text(encoding="utf-8").splitlines()
    assert execution_order[0] == "human-login"
    assert "sts get-caller-identity" in execution_order[1]
    _assert_bounded_inventory_summary(completed, status="passed")
    _assert_private_inventory_evidence(inventory)
    assert json.loads(inventory.read_text(encoding="utf-8"))["identity"] == {
        "account_id": account_id,
        "environment": "demo",
        "project": "modelguard-ai",
        "region": "us-east-1",
    }


def test_teardown_inventory_oidc_mode_uses_region_and_exact_role_without_profile(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    account_id = "123456789012"
    role_name = "modelguard-ai-ci-deploy"
    environment, capture, inventory = _teardown_test_environment(
        repository_root=repository_root,
        tmp_path=tmp_path,
        caller_arn=f"arn:aws:sts::{account_id}:assumed-role/{role_name}/modelguard-destroy-1",
    )
    environment.update(
        {
            "AWS_ACCESS_KEY_ID": "synthetic-oidc-access",
            "AWS_SECRET_ACCESS_KEY": "synthetic-oidc-secret",
            "AWS_SESSION_TOKEN": "synthetic-oidc-session",
            "EXPECTED_AWS_ROLE_ARN": (
                f"arn:aws:iam::{account_id}:role/modelguard-ai/bootstrap/{role_name}"
            ),
            "GITHUB_ACTIONS": "true",
        }
    )

    completed = _run_teardown_verifier(
        repository_root=repository_root,
        environment=environment,
    )

    assert completed.returncode == 0, completed.stderr
    calls = _captured_aws_calls(capture)
    assert len(calls) >= 20
    assert all(call[:2] == ["--region", "us-east-1"] for call in calls)
    assert all("--profile" not in call for call in calls)
    assert calls[0][2:4] == ["sts", "get-caller-identity"]
    assert not (tmp_path / "human-login-calls.jsonl").exists()
    _assert_bounded_inventory_summary(completed, status="passed")
    for synthetic_secret in (
        "synthetic-oidc-access",
        "synthetic-oidc-secret",
        "synthetic-oidc-session",
    ):
        assert synthetic_secret not in completed.stdout + completed.stderr
    _assert_private_inventory_evidence(inventory)


@pytest.mark.parametrize(
    "credential_overrides",
    (
        {
            "AWS_ACCESS_KEY_ID": "synthetic-static-access",
            "AWS_SECRET_ACCESS_KEY": "synthetic-static-secret",
        },
        {"FAKE_HUMAN_CREDENTIAL_METHOD": "shared-credentials-file"},
    ),
)
def test_teardown_inventory_human_mode_refuses_non_login_credentials_before_aws(
    repository_root: Path,
    tmp_path: Path,
    credential_overrides: dict[str, str],
) -> None:
    account_id = "123456789012"
    environment, capture, inventory = _teardown_test_environment(
        repository_root=repository_root,
        tmp_path=tmp_path,
        caller_arn=f"arn:aws:iam::{account_id}:user/modelguard-bootstrap-admin",
    )
    environment.update(
        {
            "AWS_PROFILE": "modelguard-bootstrap",
            **credential_overrides,
        }
    )

    completed = _run_teardown_verifier(
        repository_root=repository_root,
        environment=environment,
    )

    assert completed.returncode == 1
    assert completed.stdout == (
        "Refusing inventory: temporary browser-login credential verification failed.\n"
    )
    assert completed.stderr == ""
    assert len(_captured_human_login_calls(tmp_path)) == 1
    assert not capture.exists()
    assert not inventory.exists()
    for private_value in credential_overrides.values():
        assert private_value not in completed.stdout + completed.stderr


def test_teardown_inventory_creates_private_parent_and_preserves_distinct_attempts(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    account_id = "123456789012"
    environment, _, _ = _teardown_test_environment(
        repository_root=repository_root,
        tmp_path=tmp_path,
        caller_arn=f"arn:aws:iam::{account_id}:user/modelguard-bootstrap-admin",
    )
    environment["AWS_PROFILE"] = "modelguard-bootstrap"
    tmp_path.chmod(0o755)
    attempt_parent = tmp_path / "inventory-attempts"
    first_receipt = attempt_parent / "post-destroy-attempt-1.json"
    second_receipt = attempt_parent / "post-destroy-attempt-2.json"
    environment["INVENTORY_OUTPUT"] = str(first_receipt)

    first = _run_teardown_verifier(
        repository_root=repository_root,
        environment=environment,
    )

    assert first.returncode == 0, first.stderr
    _assert_bounded_inventory_summary(first, status="passed")
    _assert_private_inventory_evidence(first_receipt)
    first_payload = first_receipt.read_bytes()

    environment["INVENTORY_OUTPUT"] = str(second_receipt)
    second = _run_teardown_verifier(
        repository_root=repository_root,
        environment=environment,
    )

    assert second.returncode == 0, second.stderr
    _assert_bounded_inventory_summary(second, status="passed")
    _assert_private_inventory_evidence(second_receipt)
    assert first_receipt.read_bytes() == first_payload
    assert first_receipt != second_receipt
    assert tmp_path.stat().st_mode & 0o777 == 0o755


def test_teardown_inventory_never_chmods_a_caller_selected_existing_parent(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    account_id = "123456789012"
    environment, capture, _ = _teardown_test_environment(
        repository_root=repository_root,
        tmp_path=tmp_path,
        caller_arn=f"arn:aws:iam::{account_id}:user/modelguard-bootstrap-admin",
    )
    environment["AWS_PROFILE"] = "modelguard-bootstrap"
    caller_parent = tmp_path / "caller-selected"
    caller_parent.mkdir(mode=0o755)
    caller_parent.chmod(0o755)
    inventory = caller_parent / "post-destroy.json"
    environment["INVENTORY_OUTPUT"] = str(inventory)

    completed = _run_teardown_verifier(
        repository_root=repository_root,
        environment=environment,
    )

    assert completed.returncode == 1
    assert "output parent must already be owner-only" in completed.stdout
    assert completed.stderr == ""
    assert caller_parent.stat().st_mode & 0o777 == 0o755
    assert not inventory.exists()
    assert len(_captured_aws_calls(capture)) == 1


def test_teardown_inventory_refuses_to_overwrite_the_first_receipt(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    account_id = "123456789012"
    environment, capture, inventory = _teardown_test_environment(
        repository_root=repository_root,
        tmp_path=tmp_path,
        caller_arn=f"arn:aws:iam::{account_id}:user/modelguard-bootstrap-admin",
    )
    environment["AWS_PROFILE"] = "modelguard-bootstrap"
    original = b'{"sealed":"first-attempt"}\n'
    inventory.write_bytes(original)
    inventory.chmod(0o600)

    completed = _run_teardown_verifier(
        repository_root=repository_root,
        environment=environment,
    )

    assert completed.returncode == 1
    assert "output must be a new path" in completed.stdout
    assert completed.stderr == ""
    assert inventory.read_bytes() == original
    assert len(_captured_aws_calls(capture)) == 1


def test_teardown_inventory_suppresses_partial_aws_output_and_error_values(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    account_id = "123456789012"
    raw_arn = f"arn:aws:iam::{account_id}:role/private-error-sentinel"
    raw_stdout = f'{{"Account":"{account_id}","Arn":"{raw_arn}"}}'
    raw_stderr = f"AccessDenied for {raw_arn} in account {account_id}"
    environment, capture, inventory = _teardown_test_environment(
        repository_root=repository_root,
        tmp_path=tmp_path,
        caller_arn=f"arn:aws:iam::{account_id}:user/modelguard-bootstrap-admin",
    )
    diagnostic_root = tmp_path / "diagnostic-temp"
    diagnostic_root.mkdir(mode=0o700)
    environment.update(
        {
            "AWS_PROFILE": "modelguard-bootstrap",
            "FAKE_AWS_FAIL_SERVICE": "resourcegroupstaggingapi",
            "FAKE_AWS_STDERR_SENTINEL": raw_stderr,
            "FAKE_AWS_STDOUT_SENTINEL": raw_stdout,
            "TMPDIR": str(diagnostic_root),
        }
    )

    completed = _run_teardown_verifier(
        repository_root=repository_root,
        environment=environment,
    )

    assert completed.returncode == 91
    assert completed.stdout == ""
    assert completed.stderr == "Refusing inventory: an AWS inventory query failed.\n"
    combined_output = completed.stdout + completed.stderr
    assert raw_stdout not in combined_output
    assert raw_stderr not in combined_output
    assert raw_arn not in combined_output
    assert account_id not in combined_output
    calls = _captured_aws_calls(capture)
    assert len(calls) == 2
    assert calls[0][4:6] == ["sts", "get-caller-identity"]
    assert calls[1][4:6] == ["resourcegroupstaggingapi", "get-resources"]
    assert not inventory.exists()
    assert list(diagnostic_root.iterdir()) == []


def test_teardown_inventory_combines_composite_alarms_and_refuses_the_residual(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    account_id = "123456789012"
    composite_alarm = (
        f"arn:aws:cloudwatch:us-east-1:{account_id}:alarm:modelguard-ai-demo-composite"
    )
    environment, capture, inventory = _teardown_test_environment(
        repository_root=repository_root,
        tmp_path=tmp_path,
        caller_arn=f"arn:aws:iam::{account_id}:user/modelguard-bootstrap-admin",
    )
    environment.update(
        {
            "AWS_PROFILE": "modelguard-bootstrap",
            "FAKE_COMPOSITE_ALARM_ARN": composite_alarm,
        }
    )

    completed = _run_teardown_verifier(
        repository_root=repository_root,
        environment=environment,
    )

    assert completed.returncode == 2
    summary = _assert_bounded_inventory_summary(
        completed,
        status="refused",
        residual_service_count=1,
    )
    assert summary["reason"] == "post_destroy_demo_resources_remain"
    assert composite_alarm not in completed.stdout + completed.stderr
    _assert_private_inventory_evidence(inventory)
    cloudwatch_call = next(
        call
        for call in _captured_aws_calls(capture)
        if "cloudwatch" in call and "describe-alarms" in call
    )
    query = cloudwatch_call[cloudwatch_call.index("--query") + 1]
    assert "MetricAlarms" in query
    assert "CompositeAlarms" in query


@pytest.mark.parametrize(
    ("overrides", "reason"),
    (
        ({}, "browser-login AWS_PROFILE is required"),
        ({"AWS_PROFILE": "default"}, "AWS_PROFILE must be modelguard-bootstrap"),
        ({"GITHUB_ACTIONS": "true"}, "EXPECTED_AWS_ROLE_ARN is required"),
        (
            {
                "AWS_PROFILE": "modelguard-bootstrap",
                "GITHUB_ACTIONS": "true",
            },
            "GitHub OIDC mode forbids AWS profile selection",
        ),
        (
            {
                "AWS_DEFAULT_PROFILE": "default",
                "GITHUB_ACTIONS": "true",
            },
            "GitHub OIDC mode forbids AWS profile selection",
        ),
        (
            {
                "EXPECTED_AWS_ROLE_ARN": "arn:aws:iam::123456789012:role/other",
                "GITHUB_ACTIONS": "true",
            },
            "EXPECTED_AWS_ROLE_ARN is not the approved teardown role",
        ),
        (
            {
                "AWS_PROFILE": "modelguard-bootstrap",
                "EXPECTED_AWS_ROLE_ARN": (
                    "arn:aws:iam::123456789012:role/modelguard-ai/bootstrap/modelguard-ai-ci-deploy"
                ),
            },
            "browser-profile mode forbids EXPECTED_AWS_ROLE_ARN",
        ),
        (
            {"AWS_PROFILE": "modelguard-bootstrap", "AWS_REGION": "eu-west-1"},
            "AWS_REGION must be the canonical Region",
        ),
    ),
)
def test_teardown_inventory_refuses_missing_or_mixed_identity_mode_before_aws(
    repository_root: Path,
    tmp_path: Path,
    overrides: dict[str, str],
    reason: str,
) -> None:
    environment, capture, inventory = _teardown_test_environment(
        repository_root=repository_root,
        tmp_path=tmp_path,
        caller_arn=("arn:aws:iam::123456789012:user/modelguard-bootstrap-admin"),
    )
    environment.update(overrides)

    completed = _run_teardown_verifier(
        repository_root=repository_root,
        environment=environment,
    )

    assert completed.returncode == 1
    assert reason in completed.stdout
    assert "123456789012" not in completed.stdout + completed.stderr
    assert "arn:aws:" not in completed.stdout + completed.stderr
    assert not capture.exists()
    assert not inventory.exists()


@pytest.mark.parametrize(
    ("github_actions", "caller_arn", "expected_reason"),
    (
        (
            False,
            "arn:aws:iam::123456789012:user/another-user",
            "exact approved non-root browser identity",
        ),
        (
            True,
            "arn:aws:sts::123456789012:assumed-role/another-role/session",
            "exact approved GitHub OIDC role",
        ),
    ),
)
def test_teardown_inventory_refuses_wrong_caller_after_only_the_sts_query(
    repository_root: Path,
    tmp_path: Path,
    github_actions: bool,
    caller_arn: str,
    expected_reason: str,
) -> None:
    account_id = "123456789012"
    environment, capture, inventory = _teardown_test_environment(
        repository_root=repository_root,
        tmp_path=tmp_path,
        caller_arn=caller_arn,
    )
    if github_actions:
        environment.update(
            {
                "EXPECTED_AWS_ROLE_ARN": (
                    f"arn:aws:iam::{account_id}:role/modelguard-ai/bootstrap/"
                    "modelguard-ai-ci-deploy"
                ),
                "GITHUB_ACTIONS": "true",
            }
        )
    else:
        environment["AWS_PROFILE"] = "modelguard-bootstrap"

    completed = _run_teardown_verifier(
        repository_root=repository_root,
        environment=environment,
    )

    assert completed.returncode == 1
    assert expected_reason in completed.stdout
    assert caller_arn not in completed.stdout + completed.stderr
    assert account_id not in completed.stdout + completed.stderr
    calls = _captured_aws_calls(capture)
    assert len(calls) == 1
    service_index = 4 if "--profile" in calls[0] else 2
    assert calls[0][service_index : service_index + 2] == ["sts", "get-caller-identity"]
    assert not inventory.exists()


def test_teardown_inventory_refuses_wrong_account_after_only_the_sts_query(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    approved_account = "123456789012"
    other_account = "999999999999"
    caller_arn = f"arn:aws:iam::{other_account}:user/modelguard-bootstrap-admin"
    environment, capture, inventory = _teardown_test_environment(
        repository_root=repository_root,
        tmp_path=tmp_path,
        caller_arn=caller_arn,
    )
    environment.update(
        {
            "AWS_PROFILE": "modelguard-bootstrap",
            "FAKE_CALLER_ACCOUNT": other_account,
        }
    )

    completed = _run_teardown_verifier(
        repository_root=repository_root,
        environment=environment,
    )

    assert completed.returncode == 1
    assert "caller account does not match" in completed.stdout
    combined_output = completed.stdout + completed.stderr
    assert approved_account not in combined_output
    assert other_account not in combined_output
    assert caller_arn not in combined_output
    assert len(_captured_aws_calls(capture)) == 1
    assert not inventory.exists()


def test_post_destroy_inventory_v2_classifies_strict_retained_evidence() -> None:
    payload = _post_destroy_inventory()
    payload["ResourceTagMappingList"] = [
        {
            "ResourceARN": "arn:aws:ecs:us-east-1:123456789012:cluster/modelguard-ai-demo",
            "Tags": [
                {"Key": "Project", "Value": "modelguard-ai"},
                {"Key": "Environment", "Value": "demo"},
                {"Key": "Ownership", "Value": "demo"},
            ],
        }
    ]
    inactive = [
        "arn:aws:ecs:us-east-1:123456789012:task-definition/"
        f"modelguard-ai-demo-{component}:{revision}"
        for revision, component in enumerate(("api", "dashboard", "monitor"), start=1)
    ]
    payload["nonbillable_metadata"]["ecs_task_definitions_inactive"] = inactive

    result = _evaluate_post_destroy_inventory(payload)
    assert result["residual_demo"] == [
        "arn:aws:ecs:us-east-1:123456789012:cluster/modelguard-ai-demo"
    ]
    assert result["retained_bootstrap"] == []
    assert result["retained_budget"] == ["modelguard-ai-demo-monthly"]
    assert result["residual_service"] == []
    assert result["validated_nonbillable"] == [
        f"ecs_task_definitions_inactive:{identifier}" for identifier in inactive
    ]


@pytest.mark.parametrize(
    "budgets",
    (
        [],
        ["another-budget"],
        ["modelguard-ai-demo-monthly", "another-budget"],
        ["modelguard-ai-demo-monthly", "modelguard-ai-demo-monthly"],
    ),
)
def test_post_destroy_inventory_v2_requires_only_the_exact_budget(budgets: list[str]) -> None:
    payload = _post_destroy_inventory()
    payload["retained_resources"]["budgets"] = budgets
    with pytest.raises(GuardError, match="inventory_retained_budget_invalid"):
        _evaluate_post_destroy_inventory(payload)


@pytest.mark.parametrize(
    "identifier",
    (
        "arn:aws:ecs:us-east-1:123456789012:task-definition/modelguard-ai-demo-worker:1",
        "arn:aws:ecs:us-east-1:999999999999:task-definition/modelguard-ai-demo-api:1",
        "arn:aws:ecs:eu-west-1:123456789012:task-definition/modelguard-ai-demo-api:1",
        "arn:aws:ecs:us-east-1:123456789012:task-definition/modelguard-ai-demo-api:0",
        "not-an-arn",
    ),
)
def test_post_destroy_inventory_v2_rejects_foreign_or_malformed_inactive_metadata(
    identifier: str,
) -> None:
    payload = _post_destroy_inventory()
    payload["nonbillable_metadata"]["ecs_task_definitions_inactive"] = [identifier]
    with pytest.raises(GuardError, match="inventory_inactive_task_definition_invalid"):
        _evaluate_post_destroy_inventory(payload)


@pytest.mark.parametrize(
    ("mutation", "error"),
    (
        ("wrong_schema", "inventory_schema_version_invalid"),
        ("unknown_top_level", "inventory_schema_fields_mismatch"),
        ("unknown_service", "inventory_service_residuals_invalid"),
        ("missing_service", "inventory_service_residuals_invalid"),
        ("unknown_retained", "inventory_retained_resources_invalid"),
        ("unknown_metadata", "inventory_nonbillable_metadata_invalid"),
    ),
)
def test_post_destroy_inventory_v2_rejects_unknown_or_incomplete_schema(
    mutation: str,
    error: str,
) -> None:
    payload = _post_destroy_inventory()
    if mutation == "wrong_schema":
        payload["schema_version"] = "modelguard.post-destroy-inventory.v1"
    elif mutation == "unknown_top_level":
        payload["unknown"] = []
    elif mutation == "unknown_service":
        payload["service_residuals"]["unknown"] = []
    elif mutation == "missing_service":
        del payload["service_residuals"]["alarms"]
    elif mutation == "unknown_retained":
        payload["retained_resources"]["unknown"] = []
    else:
        payload["nonbillable_metadata"]["unknown"] = []
    with pytest.raises(GuardError, match=error):
        _evaluate_post_destroy_inventory(payload)


@pytest.mark.parametrize("mutation", ("lowercase_aliases", "extra_field"))
def test_post_destroy_inventory_v2_requires_exact_resource_mapping_fields(
    mutation: str,
) -> None:
    payload = _post_destroy_inventory()
    canonical = {
        "ResourceARN": "arn:aws:ecs:us-east-1:123456789012:cluster/modelguard-ai-demo",
        "Tags": [],
    }
    if mutation == "lowercase_aliases":
        payload["ResourceTagMappingList"] = [
            {"arn": canonical["ResourceARN"], "tags": canonical["Tags"]}
        ]
    else:
        payload["ResourceTagMappingList"] = [{**canonical, "Unexpected": "value"}]

    with pytest.raises(GuardError, match="inventory_resource_invalid"):
        _evaluate_post_destroy_inventory(payload)


@pytest.mark.parametrize(
    "tags",
    (
        [],
        [{"Key": "Project", "Value": "modelguard-ai"}],
        [
            {"Key": "Project", "Value": "modelguard-ai"},
            {"Key": "Environment", "Value": "bootstrap"},
        ],
        [
            {"Key": "Project", "Value": "another-project"},
            {"Key": "Environment", "Value": "demo"},
        ],
    ),
)
def test_post_destroy_inventory_v2_refuses_tag_results_outside_the_exact_query_scope(
    tags: list[dict[str, str]],
) -> None:
    payload = _post_destroy_inventory()
    payload["ResourceTagMappingList"] = [
        {
            "ResourceARN": ("arn:aws:ecs:us-east-1:123456789012:cluster/modelguard-ai-demo"),
            "Tags": tags,
        }
    ]

    with pytest.raises(GuardError, match="inventory_resource_tag_scope_mismatch"):
        _evaluate_post_destroy_inventory(payload)


@pytest.mark.parametrize(
    ("identity_field", "forged_value"),
    (
        ("account_id", "999999999999"),
        ("region", "eu-west-1"),
    ),
)
def test_post_destroy_inventory_cli_refuses_forged_identity_without_value_leakage(
    repository_root: Path,
    tmp_path: Path,
    identity_field: str,
    forged_value: str,
) -> None:
    tmp_path.chmod(0o700)
    payload = _post_destroy_inventory()
    payload["identity"][identity_field] = forged_value
    input_path = tmp_path / f"forged-{identity_field}.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    input_path.chmod(0o600)

    completed = _run_inventory_guard(
        repository_root=repository_root,
        input_path=input_path,
    )

    assert completed.returncode == 2
    summary = _assert_bounded_inventory_summary(completed, status="refused")
    assert summary["reason"] == "inventory_identity_mismatch"
    assert forged_value not in completed.stdout + completed.stderr


@pytest.mark.parametrize("unsafe_kind", ("file_symlink", "parent_symlink", "file_mode"))
def test_post_destroy_inventory_cli_refuses_unsafe_evidence_without_printing_it(
    repository_root: Path,
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    tmp_path.chmod(0o700)
    private_parent = tmp_path / "private"
    private_parent.mkdir(mode=0o700)
    private_parent.chmod(0o700)
    raw_marker = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:must-not-print"
    payload = _post_destroy_inventory()
    payload["service_residuals"]["alarms"] = [raw_marker]
    target = private_parent / "target.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    target.chmod(0o600)
    if unsafe_kind == "file_symlink":
        input_path = private_parent / "inventory.json"
        input_path.symlink_to(target)
    elif unsafe_kind == "parent_symlink":
        linked_parent = tmp_path / "linked"
        linked_parent.symlink_to(private_parent, target_is_directory=True)
        input_path = linked_parent / "target.json"
    else:
        target.chmod(0o640)
        input_path = target

    completed = _run_inventory_guard(
        repository_root=repository_root,
        input_path=input_path,
    )

    assert completed.returncode == 2
    summary = _assert_bounded_inventory_summary(completed, status="refused")
    assert summary["reason"].startswith("inventory_evidence_")
    assert raw_marker not in completed.stdout + completed.stderr


@pytest.mark.parametrize(
    ("malformed_prefix", "expected_reason"),
    (
        (
            '"schema_version":"do-not-log-duplicate",',
            "inventory_evidence_duplicate_key",
        ),
        ('"non_finite":NaN,', "inventory_evidence_non_finite_number"),
    ),
)
def test_post_destroy_inventory_cli_strict_json_refuses_duplicate_and_non_finite_values(
    repository_root: Path,
    tmp_path: Path,
    malformed_prefix: str,
    expected_reason: str,
) -> None:
    tmp_path.chmod(0o700)
    canonical = json.dumps(_post_destroy_inventory())
    input_path = tmp_path / "strict-inventory.json"
    input_path.write_text("{" + malformed_prefix + canonical[1:], encoding="utf-8")
    input_path.chmod(0o600)

    completed = _run_inventory_guard(
        repository_root=repository_root,
        input_path=input_path,
    )

    assert completed.returncode == 2
    summary = _assert_bounded_inventory_summary(completed, status="refused")
    assert summary["reason"] == expected_reason
    assert "do-not-log-duplicate" not in completed.stdout + completed.stderr


def test_post_destroy_inventory_v2_keeps_active_and_live_resources_fatal(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    payload = _post_destroy_inventory()
    active = "arn:aws:ecs:us-east-1:123456789012:task-definition/modelguard-ai-demo-api:2"
    payload["service_residuals"]["ecs_task_definitions_active"] = [active]
    payload["service_residuals"]["s3_buckets"] = ["modelguard-ai-demo-example-models"]
    result = _evaluate_post_destroy_inventory(payload)
    assert result["residual_service"] == [
        f"ecs_task_definitions_active:{active}",
        "s3_buckets:modelguard-ai-demo-example-models",
    ]
    input_path = tmp_path / "inventory.json"
    tmp_path.chmod(0o700)
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    input_path.chmod(0o600)
    completed = _run_inventory_guard(
        repository_root=repository_root,
        input_path=input_path,
    )
    assert completed.returncode == 2
    summary = _assert_bounded_inventory_summary(
        completed,
        status="refused",
        residual_service_count=2,
    )
    assert summary["reason"] == "post_destroy_demo_resources_remain"
    assert active not in completed.stdout + completed.stderr
    assert "modelguard-ai-demo-example-models" not in completed.stdout + completed.stderr


def test_post_destroy_inventory_v2_rejects_malformed_service_identifier() -> None:
    payload = _post_destroy_inventory()
    payload["service_residuals"]["s3_buckets"] = [""]
    with pytest.raises(GuardError, match="inventory_service_identifier_invalid"):
        _evaluate_post_destroy_inventory(payload)


def test_network_storage_runtime_and_destroy_contract_are_static_and_explicit(
    repository_root: Path,
) -> None:
    network = _read(repository_root, "infrastructure/modules/network/main.tf")
    data_plane = _read(repository_root, "infrastructure/modules/data_plane/main.tf")
    ecs_module = _read(repository_root, "infrastructure/modules/ecs_service/main.tf")
    alb = _read(repository_root, "infrastructure/environments/demo/alb.tf")
    firehose = _read(repository_root, "infrastructure/environments/demo/firehose.tf")
    destroy = _read(repository_root, "scripts/safe_destroy.sh")
    apply = _read(repository_root, "scripts/safe_apply.sh")
    teardown_inventory = _read(repository_root, "scripts/verify_aws_teardown.sh")

    assert network.count('resource "aws_subnet"') == 2
    assert 'resource "aws_nat_gateway" "this"' in network
    assert network.count('resource "aws_nat_gateway"') == 1
    assert 'vpc_endpoint_type = "Gateway"' in network
    assert "prod-${data.aws_region.current.region}-starport-layer-bucket" in network
    assert "map_public_ip_on_launch = false" in network
    assert "referenced_security_group_id = aws_security_group.alb.id" in network
    assert "assign_public_ip = false" in ecs_module
    assert "deployment_circuit_breaker" in ecs_module
    assert "rollback = true" in ecs_module
    assert 'platform_version = "LATEST"' in ecs_module
    assert 'platform_version        = "LATEST"' in _read(
        repository_root, "infrastructure/environments/demo/scheduler.tf"
    )
    assert 'name = "scratch"' in ecs_module
    assert 'containerPath = "/tmp"' in ecs_module
    assert 'image_tag_mutability = "IMMUTABLE"' in data_plane
    assert 'compression_format = "GZIP"' in firehose
    assert "year=!{timestamp:yyyy}" in firehose
    assert 'values = ["/metrics", "/metrics/*"]' in alb
    assert "verify-plan" in destroy and "verify-inventory" in teardown_inventory
    assert destroy.index("verify-plan") < destroy.index('terraform -chdir="$env_dir" apply')
    assert "verify_aws_teardown.sh" in destroy
    assert "service_residuals" in teardown_inventory
    assert "modelguard.post-destroy-inventory.v2" in teardown_inventory
    assert "umask 077" in teardown_inventory
    assert 'command aws --region "$AWS_REGION"' in teardown_inventory
    assert "aws configure get region" not in teardown_inventory
    assert 'chmod 0700 -- "$inventory_parent"' not in teardown_inventory
    assert "EXPECTED_AWS_ROLE_ARN is required in GitHub OIDC mode" in teardown_inventory
    assert "GitHub OIDC mode forbids AWS profile selection" in teardown_inventory
    assert "--status INACTIVE" in teardown_inventory
    assert "nonbillable_metadata" in teardown_inventory
    assert "retained_resources" in teardown_inventory
    service_block, retained_block = teardown_inventory.split("retained_resources:", maxsplit=1)
    assert "budgets:" not in service_block
    assert "ecs_task_definitions_inactive:" not in service_block
    assert "budgets: $budgets" in retained_block
    assert "ecs_task_definitions_inactive: $ecs_task_definitions_inactive" in retained_block
    for required_query in (
        "describe-listeners",
        "describe-rules",
        "list-object-versions",
        "list-multipart-uploads",
        "list-images",
        "list-subscriptions-by-topic",
        "CompositeAlarms[].AlarmArn",
    ):
        assert required_query in teardown_inventory
    for required_inventory in (
        "listener_rules",
        "s3_object_versions",
        "s3_multipart_uploads",
        "ecr_images",
        "sns_subscriptions",
    ):
        assert f"{required_inventory}:" in teardown_inventory
    assert 'plan_path="$env_dir/$PLAN_STAGE.tfplan"' in apply
    assert apply.count("verify-plan") == 2
    assert apply.rindex("verify-plan") < apply.index('terraform -chdir="$env_dir" apply')
    assert "terraform -target" not in apply
    assert "setequals(" not in data_plane
    assert "data.aws_region.current.name" not in network


def test_operator_scripts_refuse_without_explicit_confirmation(repository_root: Path) -> None:
    for relative in ("scripts/safe_apply.sh", "scripts/safe_destroy.sh"):
        result = subprocess.run(
            [str(repository_root / relative)],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
            env={},
        )
        assert result.returncode != 0
        assert "Refusing" in result.stdout


def test_bootstrap_iam_uses_current_budget_actions_and_scoped_managed_policies(
    repository_root: Path,
) -> None:
    iam = _read(repository_root, "infrastructure/bootstrap/iam.tf")

    assert '"budgets:ViewBudget"' in iam
    assert '"budgets:ModifyBudget"' not in iam
    assert '"aws-portal:ModifyBilling"' not in iam
    assert "budgets:DescribeBudget" not in iam
    assert "budgets:CreateBudget" not in iam
    assert "budgets:DeleteBudget" not in iam
    assert "s3:PutBucketLifecycleConfiguration" not in iam
    assert '"s3:PutLifecycleConfiguration"' in iam
    assert 'resource "aws_iam_policy" "ci_plan_read"' in iam
    assert 'resource "aws_iam_policy" "ci_deploy_compute"' in iam
    assert 'resource "aws_iam_policy" "ci_deploy_data"' in iam
    assert 'resource "aws_iam_policy" "ci_deploy_operations"' in iam
    assert 'actions   = ["ecr:GetAuthorizationToken"]' in iam
    for required_action in (
        '"ecr:CompleteLayerUpload"',
        '"ecr:DescribeImages"',
        '"ecr:InitiateLayerUpload"',
        '"ecr:PutImage"',
        '"ecr:UploadLayerPart"',
        '"s3:GetObjectVersion"',
        '"s3:ListBucketMultipartUploads"',
        '"s3:PutObject"',
    ):
        assert required_action in iam


def test_bootstrap_and_demo_state_ownership_cannot_overlap(repository_root: Path) -> None:
    bootstrap_files = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (repository_root / "infrastructure/bootstrap").glob("*.tf")
    )
    demo_files = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (repository_root / "infrastructure/environments/demo").glob("*.tf")
    )
    backend = _read(repository_root, "infrastructure/environments/demo/backend.hcl.example")
    bootstrap_lock = _read(repository_root, "infrastructure/bootstrap/.terraform.lock.hcl")
    demo_lock = _read(repository_root, "infrastructure/environments/demo/.terraform.lock.hcl")

    assert 'resource "aws_s3_bucket" "state"' in bootstrap_files
    assert 'resource "aws_iam_openid_connect_provider" "github"' in bootstrap_files
    assert 'resource "aws_iam_policy" "workload_boundary"' in bootstrap_files
    assert 'resource "aws_s3_bucket" "state"' not in demo_files
    assert "aws_iam_openid_connect_provider" not in demo_files
    assert 'backend "s3" {}' in demo_files
    assert "use_lockfile   = true" in backend
    assert "encrypt        = true" in backend
    assert "kms_key_id" in backend
    assert bootstrap_lock == demo_lock
    assert 'version     = "6.46.0"' in bootstrap_lock
    assert 'constraints = "6.46.0"' in bootstrap_lock
    assert bootstrap_lock.count('"zh:') == 15
