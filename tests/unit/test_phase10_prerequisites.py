"""Manual Budget and Firehose readiness preflight tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from scripts.aws_readiness_preflight import (
    BUDGET_NAME,
    FIREHOSE_STREAM_NAME,
    ReadinessRefusal,
    verify_budget_prerequisite,
    verify_firehose_readiness,
)
from scripts.human_aws_login import (
    HumanLoginRefusal,
    verify_human_login_identity,
    verify_workflow_oidc_identity,
)


def _error(code: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "sanitized fake"},
            "ResponseMetadata": {"HTTPStatusCode": 400},
        },
        "Describe",
    )


class BudgetDouble:
    def __init__(self, notifications: list[dict[str, Any]] | None = None) -> None:
        self.notifications = (
            notifications
            if notifications is not None
            else [
                {
                    "ComparisonOperator": "GREATER_THAN",
                    "NotificationType": basis,
                    "Threshold": threshold,
                    "ThresholdType": "PERCENTAGE",
                }
                for basis, threshold in (
                    ("ACTUAL", 50),
                    ("ACTUAL", 80),
                    ("ACTUAL", 100),
                    ("FORECASTED", 100),
                )
            ]
        )
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def describe_budget(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("describe_budget", kwargs))
        return {
            "Budget": {
                "BudgetName": BUDGET_NAME,
                "BudgetType": "COST",
                "TimeUnit": "MONTHLY",
                "BudgetLimit": {"Amount": "10.0", "Unit": "USD"},
            }
        }

    def describe_notifications_for_budget(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("describe_notifications_for_budget", kwargs))
        return {"Notifications": self.notifications}

    def describe_subscribers_for_notification(self, **kwargs: Any) -> Mapping[str, Any]:
        del kwargs
        raise AssertionError("subscriber endpoints must never be requested")


def test_budget_preflight_verifies_exact_value_and_thresholds_without_subscribers() -> None:
    client = BudgetDouble()

    result = verify_budget_prerequisite(client, account_id="123456789012")

    assert result == {
        "amount_usd": 10,
        "budget_name": BUDGET_NAME,
        "configured_thresholds": [
            {"basis": "actual", "percentage": 50},
            {"basis": "actual", "percentage": 80},
            {"basis": "actual", "percentage": 100},
            {"basis": "forecasted", "percentage": 100},
        ],
        "status": "passed",
        "subscriber_endpoints_accessed": False,
    }
    serialized = json.dumps(result)
    assert "@" not in serialized and "subscriber" in serialized
    assert [name for name, _ in client.calls] == [
        "describe_budget",
        "describe_notifications_for_budget",
    ]


@pytest.mark.parametrize(
    "notifications",
    [
        [],
        [
            {
                "ComparisonOperator": "GREATER_THAN",
                "NotificationType": "ACTUAL",
                "Threshold": 80,
                "ThresholdType": "PERCENTAGE",
            }
        ],
        [
            {
                "ComparisonOperator": "GREATER_THAN",
                "NotificationType": basis,
                "Threshold": threshold,
                "ThresholdType": "PERCENTAGE",
            }
            for basis, threshold in (
                ("ACTUAL", 50),
                ("ACTUAL", 80),
                ("ACTUAL", 100),
                ("FORECASTED", 100),
                ("FORECASTED", 50),
            )
        ],
    ],
)
def test_budget_preflight_rejects_missing_or_extra_thresholds(
    notifications: list[dict[str, Any]],
) -> None:
    with pytest.raises(ReadinessRefusal, match="budget_thresholds_incomplete"):
        verify_budget_prerequisite(BudgetDouble(notifications), account_id="123456789012")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ComparisonOperator", "LESS_THAN"),
        ("ThresholdType", "ABSOLUTE_VALUE"),
        ("NotificationType", "UNKNOWN"),
    ],
)
def test_budget_preflight_rejects_each_wrong_notification_contract_value(
    field: str,
    value: str,
) -> None:
    client = BudgetDouble()
    client.notifications[0][field] = value

    with pytest.raises(ReadinessRefusal, match="budget_notification_contract_mismatch"):
        verify_budget_prerequisite(client, account_id="123456789012")


def test_budget_preflight_rejects_duplicate_required_threshold() -> None:
    client = BudgetDouble()
    client.notifications.append(dict(client.notifications[0]))

    with pytest.raises(ReadinessRefusal, match="budget_thresholds_incomplete"):
        verify_budget_prerequisite(client, account_id="123456789012")


class FirehoseDouble:
    def __init__(self, value: Mapping[str, Any] | ClientError) -> None:
        self.value = value

    def describe_delivery_stream(self, **kwargs: Any) -> Mapping[str, Any]:
        assert kwargs == {"DeliveryStreamName": FIREHOSE_STREAM_NAME, "Limit": 1}
        if isinstance(self.value, ClientError):
            raise self.value
        return self.value


def test_firehose_preflight_distinguishes_subscription_absence_and_stream_state() -> None:
    with pytest.raises(ReadinessRefusal, match="service_subscription_required"):
        verify_firehose_readiness(FirehoseDouble(_error("SubscriptionRequiredException")))

    absent = verify_firehose_readiness(FirehoseDouble(_error("ResourceNotFoundException")))
    assert absent == {
        "delivery_stream": FIREHOSE_STREAM_NAME,
        "service_access": "available",
        "status": "stream_not_created",
    }

    active = verify_firehose_readiness(
        FirehoseDouble(
            {
                "DeliveryStreamDescription": {
                    "DeliveryStreamName": FIREHOSE_STREAM_NAME,
                    "DeliveryStreamStatus": "ACTIVE",
                }
            }
        )
    )
    assert active["status"] == "active"


def test_human_aws_helpers_require_exact_browser_login_non_root_identity() -> None:
    account = "123456789012"
    arguments = {
        "profile": "modelguard-bootstrap",
        "region": "us-east-1",
        "expected_account_id": account,
        "credential_method": "login",
        "identity": {
            "Account": account,
            "Arn": f"arn:aws:iam::{account}:user/modelguard-bootstrap-admin",
            "UserId": "AIDAEXAMPLE",
        },
        "environment_credential_names": set(),
    }
    result = verify_human_login_identity(**arguments)
    assert result["account_id_masked"] == "********9012"
    assert account not in json.dumps(result)

    mutations = (
        {"profile": "default"},
        {"region": "eu-west-1"},
        {"credential_method": "shared-credentials-file"},
        {"credential_method": "env", "environment_credential_names": {"AWS_ACCESS_KEY_ID"}},
        {"identity": {"Account": account, "Arn": f"arn:aws:iam::{account}:root"}},
        {
            "identity": {
                "Account": account,
                "Arn": f"arn:aws:sts::{account}:assumed-role/Administrator/session",
            }
        },
    )
    for mutation in mutations:
        with pytest.raises(HumanLoginRefusal):
            verify_human_login_identity(**{**arguments, **mutation})


def test_workflow_aws_helpers_require_exact_temporary_oidc_deploy_role() -> None:
    account = "123456789012"
    role = f"arn:aws:iam::{account}:role/modelguard-ai/bootstrap/modelguard-ai-ci-deploy"
    arguments = {
        "expected_account_id": account,
        "expected_role_arn": role,
        "credential_method": "env",
        "identity": {
            "Account": account,
            "Arn": (
                f"arn:aws:sts::{account}:assumed-role/modelguard-ai-ci-deploy/"
                "modelguard-readiness-123"
            ),
        },
    }
    result = verify_workflow_oidc_identity(**arguments)
    assert result["credential_source"] == "github_oidc_temporary_session"
    assert account not in json.dumps(result)

    mutations = (
        {"expected_role_arn": f"arn:aws:iam::{account}:role/Administrator"},
        {"credential_method": "shared-credentials-file"},
        {"credential_method": "login"},
        {
            "identity": {
                "Account": account,
                "Arn": f"arn:aws:iam::{account}:user/modelguard-bootstrap-admin",
            }
        },
        {
            "identity": {
                "Account": account,
                "Arn": f"arn:aws:iam::{account}:root",
            }
        },
        {
            "identity": {
                "Account": account,
                "Arn": f"arn:aws:sts::{account}:assumed-role/modelguard-ai-ci-plan/run",
            }
        },
    )
    for mutation in mutations:
        with pytest.raises(HumanLoginRefusal):
            verify_workflow_oidc_identity(**{**arguments, **mutation})


def test_workflow_readiness_and_notification_checks_bind_the_exact_oidc_role(
    repository_root: Path,
) -> None:
    deploy = (repository_root / ".github/workflows/deploy-demo.yml").read_text()
    assert deploy.count('--workflow-role-arn "$AWS_DEPLOY_ROLE_ARN"') == 3
    assert deploy.count("AWS_DEPLOY_ROLE_ARN: ${{ vars.AWS_DEPLOY_ROLE_ARN }}") == 3

    readiness = (repository_root / "scripts/aws_readiness_preflight.py").read_text()
    notification = (repository_root / "scripts/notification_enrollment.py").read_text()
    for source in (readiness, notification):
        assert "verify_workflow_oidc_identity" in source
    assert "workflow_role_arn" in readiness
    assert "workflow_role_arn" in notification


def test_demo_terraform_treats_budget_as_manual_value_free_activation_prerequisite(
    repository_root: Path,
) -> None:
    budget = (repository_root / "infrastructure/environments/demo/budget.tf").read_text()
    variables = (repository_root / "infrastructure/environments/demo/variables.tf").read_text()

    assert 'resource "aws_budgets_budget"' not in budget
    assert 'check "manual_budget_prerequisite"' in budget
    assert "var.budget_prerequisite_verified" in budget
    assert 'variable "budget_prerequisite_verified"' in variables
    assert "budget_notification_email" not in budget + variables


def test_retained_cloudtrail_design_is_separate_narrow_encrypted_and_recoverable(
    repository_root: Path,
) -> None:
    root = repository_root / "infrastructure/audit-bootstrap"
    main = (root / "main.tf").read_text()
    versions = (root / "versions.tf").read_text()
    lock = (root / ".terraform.lock.hcl").read_text()
    readme = (root / "README.md").read_text()

    assert 'version = "= 6.46.0"' in versions
    assert 'version     = "6.46.0"' in lock
    assert 'resource "aws_cloudtrail" "terraform_state_data_events"' in main
    assert 'field  = "eventCategory"' in main and 'equals = ["Data"]' in main
    assert 'field  = "resources.type"' in main and 'equals = ["AWS::S3::Object"]' in main
    assert "modelguard-ai/demo/terraform.tfstate" in main
    assert "modelguard-ai/demo/terraform.tfstate.tflock" in main
    assert 'modelguard-ai/",' not in main
    assert "equals = [" in main
    assert "starts_with" not in main
    assert "enable_log_file_validation    = true" in main
    assert "is_multi_region_trail         = false" in main
    assert 'sse_algorithm     = "aws:kms"' in main
    assert 'resource "aws_s3_bucket_public_access_block" "audit"' in main
    assert 'resource "aws_s3_bucket_lifecycle_configuration" "audit"' in main
    assert main.count("prevent_destroy = true") >= 8
    assert 'identifiers = ["cloudtrail.amazonaws.com"]' in main
    assert 'variable = "AWS:SourceArn"' in main
    assert 'variable = "AWS:SourceAccount"' in main
    assert 'variable = "kms:EncryptionContext:aws:cloudtrail:arn"' in main
    assert 'test     = "StringEquals"' in main
    assert "encrypted offline copies" in readme
    assert "usage-based charges" in readme
    assert "does not promise zero cost" in readme
    assert "No `terraform init`, `plan`, `apply`" in readme
    expected_skips = {
        "CKV_AWS_18",
        "CKV_AWS_67",
        "CKV_AWS_109",
        "CKV_AWS_111",
        "CKV_AWS_144",
        "CKV_AWS_252",
        "CKV_AWS_356",
        "CKV2_AWS_10",
        "CKV2_AWS_62",
    }
    assert {
        line.split("checkov:skip=", 1)[1].split(":", 1)[0]
        for line in main.splitlines()
        if "checkov:skip=" in line
    } == expected_skips
    for line in main.splitlines():
        if "checkov:skip=" in line:
            assert "[owner=modelguard-maintainers; expires=2026-10-31]" in line
