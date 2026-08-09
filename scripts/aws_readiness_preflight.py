#!/usr/bin/env python3
"""Value-free, read-only Budget and Firehose readiness checks."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from scripts.human_aws_login import (
    HumanLoginRefusal,
    verify_human_login_identity,
    verify_workflow_oidc_identity,
)

BUDGET_NAME = "modelguard-ai-demo-monthly"
BUDGET_AMOUNT_USD = Decimal("10")
REQUIRED_THRESHOLDS = frozenset(
    {
        ("ACTUAL", Decimal("50")),
        ("ACTUAL", Decimal("80")),
        ("ACTUAL", Decimal("100")),
        ("FORECASTED", Decimal("100")),
    }
)
FIREHOSE_STREAM_NAME = "modelguard-ai-demo-predictions"


class ReadinessRefusal(RuntimeError):
    """A read-only prerequisite is absent, malformed, or inaccessible."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class BudgetClient(Protocol):
    def describe_budget(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def describe_notifications_for_budget(self, **kwargs: Any) -> Mapping[str, Any]: ...


class FirehoseClient(Protocol):
    def describe_delivery_stream(self, **kwargs: Any) -> Mapping[str, Any]: ...


class StsClient(Protocol):
    def get_caller_identity(self, **kwargs: Any) -> Mapping[str, Any]: ...


def _decimal(value: Any, *, category: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ReadinessRefusal(category) from error
    if not parsed.is_finite():
        raise ReadinessRefusal(category)
    return parsed


def verify_budget_prerequisite(
    client: BudgetClient,
    *,
    account_id: str,
) -> dict[str, Any]:
    """Verify only budget identity and thresholds; never request subscriber endpoints."""

    if len(account_id) != 12 or not account_id.isdigit():
        raise ReadinessRefusal("aws_account_identity_invalid")
    response = client.describe_budget(AccountId=account_id, BudgetName=BUDGET_NAME)
    budget = response.get("Budget")
    if not isinstance(budget, Mapping):
        raise ReadinessRefusal("budget_response_malformed")
    limit = budget.get("BudgetLimit")
    if (
        budget.get("BudgetName") != BUDGET_NAME
        or budget.get("BudgetType") != "COST"
        or budget.get("TimeUnit") != "MONTHLY"
        or not isinstance(limit, Mapping)
        or limit.get("Unit") != "USD"
        or _decimal(limit.get("Amount"), category="budget_amount_malformed") != BUDGET_AMOUNT_USD
    ):
        raise ReadinessRefusal("budget_contract_mismatch")

    thresholds: list[tuple[str, Decimal]] = []
    token: str | None = None
    for _ in range(10):
        request: dict[str, Any] = {"AccountId": account_id, "BudgetName": BUDGET_NAME}
        if token is not None:
            request["NextToken"] = token
        notification_response = client.describe_notifications_for_budget(**request)
        notifications = notification_response.get("Notifications")
        if not isinstance(notifications, list):
            raise ReadinessRefusal("budget_notifications_malformed")
        for notification in notifications:
            if not isinstance(notification, Mapping):
                raise ReadinessRefusal("budget_notifications_malformed")
            threshold_type = notification.get("ThresholdType")
            if threshold_type is None:
                threshold_type = "PERCENTAGE"
            if (
                notification.get("ComparisonOperator") != "GREATER_THAN"
                or threshold_type != "PERCENTAGE"
                or notification.get("NotificationType") not in {"ACTUAL", "FORECASTED"}
            ):
                raise ReadinessRefusal("budget_notification_contract_mismatch")
            thresholds.append(
                (
                    str(notification["NotificationType"]),
                    _decimal(
                        notification.get("Threshold"),
                        category="budget_threshold_malformed",
                    ),
                )
            )
        next_token = notification_response.get("NextToken")
        if next_token is None:
            break
        if not isinstance(next_token, str) or not next_token or next_token == token:
            raise ReadinessRefusal("budget_notification_pagination_malformed")
        token = next_token
    else:
        raise ReadinessRefusal("budget_notification_pagination_exceeded")
    if len(thresholds) != len(REQUIRED_THRESHOLDS) or set(thresholds) != REQUIRED_THRESHOLDS:
        raise ReadinessRefusal("budget_thresholds_incomplete")
    return {
        "amount_usd": 10,
        "budget_name": BUDGET_NAME,
        "configured_thresholds": [
            {"basis": basis.lower(), "percentage": int(percentage)}
            for basis, percentage in sorted(REQUIRED_THRESHOLDS)
        ],
        "status": "passed",
        "subscriber_endpoints_accessed": False,
    }


def verify_firehose_readiness(client: FirehoseClient) -> dict[str, Any]:
    """Distinguish service subscription from delivery-stream existence without fallback."""

    try:
        response = client.describe_delivery_stream(
            DeliveryStreamName=FIREHOSE_STREAM_NAME,
            Limit=1,
        )
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code == "SubscriptionRequiredException":
            raise ReadinessRefusal("firehose_service_subscription_required") from error
        if code in {"ResourceNotFoundException", "ResourceNotFound"}:
            return {
                "delivery_stream": FIREHOSE_STREAM_NAME,
                "service_access": "available",
                "status": "stream_not_created",
            }
        if code in {"AccessDeniedException", "AccessDenied"}:
            raise ReadinessRefusal("firehose_permission_denied") from error
        raise ReadinessRefusal("firehose_readiness_check_failed") from error
    description = response.get("DeliveryStreamDescription")
    if not isinstance(description, Mapping):
        raise ReadinessRefusal("firehose_response_malformed")
    if description.get("DeliveryStreamName") != FIREHOSE_STREAM_NAME:
        raise ReadinessRefusal("firehose_stream_identity_mismatch")
    status = description.get("DeliveryStreamStatus")
    if status not in {"ACTIVE", "CREATING"}:
        raise ReadinessRefusal("firehose_stream_not_ready")
    return {
        "delivery_stream": FIREHOSE_STREAM_NAME,
        "service_access": "available",
        "status": str(status).lower(),
    }


def _clients(
    profile: str | None, region: str
) -> tuple[BudgetClient, FirehoseClient, StsClient, str | None]:
    config = Config(
        connect_timeout=1.0,
        read_timeout=5.0,
        retries={"max_attempts": 2, "mode": "standard"},
        user_agent_extra="modelguard-readiness-preflight/1",
    )
    session = boto3.Session(profile_name=profile, region_name=region)
    credentials = session.get_credentials()
    return (
        cast(BudgetClient, session.client("budgets", region_name="us-east-1", config=config)),
        cast(FirehoseClient, session.client("firehose", region_name=region, config=config)),
        cast(StsClient, session.client("sts", region_name=region, config=config)),
        None if credentials is None else credentials.method,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aws-readiness-preflight")
    parser.add_argument("check", choices=("budget", "firehose", "all"))
    parser.add_argument("--profile")
    parser.add_argument("--workflow-role-arn")
    parser.add_argument("--region", default="us-east-1", choices=("us-east-1",))
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        workflow_mode = os.environ.get("GITHUB_ACTIONS") == "true"
        if arguments.profile is None and not workflow_mode:
            raise ReadinessRefusal("explicit_human_browser_profile_required")
        if arguments.profile is not None and arguments.workflow_role_arn is not None:
            raise ReadinessRefusal("human_and_workflow_identity_modes_conflict")
        if workflow_mode and (arguments.profile is not None or arguments.workflow_role_arn is None):
            raise ReadinessRefusal("exact_workflow_oidc_role_required")
        budgets, firehose, sts, credential_method = _clients(arguments.profile, arguments.region)
        identity = sts.get_caller_identity()
        account_id = identity.get("Account")
        if not isinstance(account_id, str):
            raise ReadinessRefusal("aws_account_identity_invalid")
        if arguments.profile is not None:
            verify_human_login_identity(
                profile=arguments.profile,
                region=arguments.region,
                expected_account_id=account_id,
                credential_method=credential_method,
                identity=identity,
                environment_credential_names={
                    name
                    for name in (
                        "AWS_ACCESS_KEY_ID",
                        "AWS_SECRET_ACCESS_KEY",
                        "AWS_SESSION_TOKEN",
                    )
                    if name in os.environ
                },
            )
        else:
            verify_workflow_oidc_identity(
                expected_account_id=account_id,
                expected_role_arn=arguments.workflow_role_arn,
                credential_method=credential_method,
                identity=identity,
            )
        results: dict[str, Any] = {}
        if arguments.check in {"budget", "all"}:
            results["budget"] = verify_budget_prerequisite(budgets, account_id=account_id)
        if arguments.check in {"firehose", "all"}:
            results["firehose"] = verify_firehose_readiness(firehose)
    except (HumanLoginRefusal, ReadinessRefusal) as error:
        reason = error.category if isinstance(error, ReadinessRefusal) else str(error)
        print(json.dumps({"reason": reason, "status": "refused"}, sort_keys=True))
        return 2
    except (BotoCoreError, ClientError, TimeoutError):
        print(
            json.dumps(
                {"reason": "aws_read_only_check_failed", "status": "refused"},
                sort_keys=True,
            )
        )
        return 3
    print(json.dumps({"checks": results, "status": "passed"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
