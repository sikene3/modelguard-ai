"""Phase 08 Terraform ownership, activation, IAM, telemetry, and teardown static gates."""

from __future__ import annotations

import json
import subprocess
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
        "backend_bucket": "modelguard-ai-terraform-state-123456789012-us-east-1",
        "backend_key": "modelguard-ai/demo/terraform.tfstate",
        "workspace": "default",
        "stage": "activation" if activation else "prerequisites",
        "activate_services": activation,
        "runtime_contract_verified": activation,
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
        "budget_notification_confirmed": True,
        "budget_notification_email": "operator" + "@" + "example.test",
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
        ("activate_services", False),
        ("runtime_contract_verified", False),
        ("alb_allowed_cidr", "0.0.0.0/0"),
        ("prediction_token_ssm_arn", "raw-token-bytes"),
        ("acm_certificate_arn", None),
        ("budget_notification_confirmed", False),
        ("active_pointer", None),
        ("image_refs", {"api": None, "dashboard": None, "monitor": None}),
        ("backend_key", "other.tfstate"),
        ("backend_bucket", "other-state-bucket"),
        ("model_bucket", "other-model-bucket"),
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


def test_saved_plan_manifest_binds_hash_identity_stage_and_expiry(
    tmp_path: Path,
    repository_root: Path,
) -> None:
    plan = tmp_path / "prerequisites.tfplan"
    variables = tmp_path / "demo.tfvars"
    backend = tmp_path / "backend.hcl"
    plan.write_bytes(b"opaque-saved-plan")
    variables.write_text("activate_services = false\n", encoding="utf-8")
    backend.write_text(
        'bucket = "modelguard-ai-terraform-state-123456789012-us-east-1"\n'
        'key = "modelguard-ai/demo/terraform.tfstate"\n'
        'region = "us-east-1"\n'
        "encrypt = true\n"
        'kms_key_id = "arn:aws:kms:us-east-1:123456789012:key/example"\n'
        "use_lockfile = true\n",
        encoding="utf-8",
    )
    today = datetime.now(tz=UTC).date()
    manifest = seal_plan(
        plan_path=plan,
        variable_file=variables,
        backend_config=backend,
        stage="prerequisites",
        account_id="123456789012",
        region="us-east-1",
        auto_destroy_date=today + timedelta(days=7),
        activate_services=False,
        repository=repository_root,
        now=datetime.now(tz=UTC),
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

    plan.write_bytes(b"opaque-saved-plan")
    backend.write_text(
        backend.read_text(encoding="utf-8").replace(
            "arn:aws:kms:us-east-1:123456789012:key/example",
            "arn:aws:kms:eu-west-1:123456789012:key/example",
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
            auto_destroy_date=today + timedelta(days=7),
            activate_services=False,
            repository=repository_root,
        )


def test_expired_reminder_never_blocks_an_exact_destroy_plan(
    tmp_path: Path,
    repository_root: Path,
) -> None:
    plan = tmp_path / "destroy.tfplan"
    variables = tmp_path / "demo.tfvars"
    backend = tmp_path / "backend.hcl"
    plan.write_bytes(b"opaque-destroy-plan")
    variables.write_text("activate_services = true\n", encoding="utf-8")
    backend.write_text(
        'bucket = "modelguard-ai-terraform-state-123456789012-us-east-1"\n'
        'key = "modelguard-ai/demo/terraform.tfstate"\n'
        'region = "us-east-1"\n'
        "encrypt = true\n"
        'kms_key_id = "arn:aws:kms:us-east-1:123456789012:key/example"\n'
        "use_lockfile = true\n",
        encoding="utf-8",
    )
    today = datetime.now(tz=UTC).date()
    manifest = seal_plan(
        plan_path=plan,
        variable_file=variables,
        backend_config=backend,
        stage="destroy",
        account_id="123456789012",
        region="us-east-1",
        auto_destroy_date=today - timedelta(days=1),
        activate_services=True,
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
    assert "runtime_desired_count" in locals
    assert 'resource "terraform_data" "deployment_guard"' in locals
    assert locals.count("precondition {") >= 10
    assert "must exactly match monitor_schedule_expression" in locals
    assert "schedule_period_seconds" in locals
    assert "expected_bundle_filenames" in locals
    assert "var.activate_services ? 1 : 0" in locals
    assert 'monitor_schedule_state = var.activate_services ? "ENABLED" : "DISABLED"' in locals
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
    assert '"repo:${var.github_repository}:ref:refs/heads/main"' in bootstrap
    assert (
        '"repo:${var.github_repository}:environment:${var.github_deploy_environment}"' in bootstrap
    )
    assert (
        '"repo:${var.github_repository}:environment:${var.github_destroy_environment}"' in bootstrap
    )
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


def test_post_destroy_inventory_fails_on_demo_and_reports_bootstrap_separately() -> None:
    payload = {
        "ResourceTagMappingList": [
            {
                "ResourceARN": "arn:aws:ecs:us-east-1:123456789012:cluster/modelguard-ai-demo",
                "Tags": [
                    {"Key": "Project", "Value": "modelguard-ai"},
                    {"Key": "Environment", "Value": "demo"},
                    {"Key": "Ownership", "Value": "demo"},
                ],
            },
            {
                "ResourceARN": "arn:aws:s3:::modelguard-ai-terraform-state-example",
                "Tags": [
                    {"Key": "Project", "Value": "modelguard-ai"},
                    {"Key": "Environment", "Value": "bootstrap"},
                    {"Key": "Ownership", "Value": "bootstrap"},
                ],
            },
        ]
    }
    result = evaluate_post_destroy_inventory(payload)
    assert result["residual_demo"] == [
        "arn:aws:ecs:us-east-1:123456789012:cluster/modelguard-ai-demo"
    ]
    assert result["retained_bootstrap"] == ["arn:aws:s3:::modelguard-ai-terraform-state-example"]
    assert evaluate_post_destroy_inventory({"resources": []})["residual_demo"] == []
    service_result = evaluate_post_destroy_inventory(
        {
            "resources": [],
            "service_residuals": {
                "inactive_task_definitions": [
                    "arn:aws:ecs:us-east-1:123456789012:task-definition/modelguard-ai-demo-api:1"
                ]
            },
        }
    )
    assert service_result["residual_service"] == [
        "inactive_task_definitions:"
        "arn:aws:ecs:us-east-1:123456789012:task-definition/modelguard-ai-demo-api:1"
    ]
    with pytest.raises(GuardError, match="inventory_service_identifier_invalid"):
        evaluate_post_destroy_inventory(
            {"resources": [], "service_residuals": {"s3_buckets": [""]}}
        )


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
    assert "--status INACTIVE" in teardown_inventory
    for required_query in (
        "describe-listeners",
        "describe-rules",
        "list-object-versions",
        "list-multipart-uploads",
        "list-images",
        "list-subscriptions-by-topic",
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
        assert result.returncode == 1
        assert "Refusing" in result.stdout


def test_bootstrap_iam_uses_current_budget_actions_and_scoped_managed_policies(
    repository_root: Path,
) -> None:
    iam = _read(repository_root, "infrastructure/bootstrap/iam.tf")

    assert '"budgets:ViewBudget"' in iam
    assert '"budgets:ModifyBudget"' in iam
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
