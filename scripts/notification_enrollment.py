#!/usr/bin/env python3
"""Enroll and verify notification subscribers without Terraform or persisted PII."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from collections.abc import Mapping
from typing import Any, Protocol, cast

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from scripts.human_aws_login import (
    APPROVED_PROFILE,
    HumanLoginRefusal,
    verify_human_login_identity,
    verify_workflow_oidc_identity,
)

ACCOUNT_PATTERN = re.compile(r"^[0-9]{12}$")
REGION_PATTERN = re.compile(r"^[a-z]{2}(-[a-z]+)+-[0-9]+$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TOPIC_NAME = "modelguard-ai-demo-alerts"
ENROLL_CONFIRMATION = "ENROLL modelguard-ai notifications"


class NotificationEnrollmentError(RuntimeError):
    """A value-free refusal safe to expose to an operator or CI log."""


class StsClient(Protocol):
    """Narrow STS client boundary used by enrollment and verification."""

    def get_caller_identity(self) -> dict[str, Any]: ...


class SnsClient(Protocol):
    """Narrow SNS client boundary."""

    def list_subscriptions_by_topic(self, **kwargs: Any) -> dict[str, Any]: ...

    def subscribe(self, **kwargs: Any) -> dict[str, Any]: ...


def _validate_identity(account_id: str, region: str) -> None:
    if ACCOUNT_PATTERN.fullmatch(account_id) is None:
        raise NotificationEnrollmentError("account_id_invalid")
    if REGION_PATTERN.fullmatch(region) is None:
        raise NotificationEnrollmentError("region_invalid")


def _validate_email(value: str, *, required: bool) -> str | None:
    candidate = value.strip()
    if not candidate and not required:
        return None
    if (
        not candidate
        or len(candidate) > 254
        or EMAIL_PATTERN.fullmatch(candidate) is None
        or candidate.casefold().endswith(".invalid")
        or any(ord(character) < 32 for character in candidate)
    ):
        raise NotificationEnrollmentError("notification_address_invalid")
    return candidate


def _sns_subscriptions(client: SnsClient, topic_arn: str) -> list[dict[str, Any]]:
    subscriptions: list[dict[str, Any]] = []
    token: str | None = None
    seen_tokens: set[str] = set()
    for _ in range(100):
        arguments: dict[str, Any] = {"TopicArn": topic_arn}
        if token is not None:
            arguments["NextToken"] = token
        response = client.list_subscriptions_by_topic(**arguments)
        subscriptions.extend(
            dict(item) for item in response.get("Subscriptions", []) if isinstance(item, Mapping)
        )
        next_token = response.get("NextToken")
        if next_token is None:
            return subscriptions
        if (
            not isinstance(next_token, str)
            or not next_token
            or next_token == token
            or next_token in seen_tokens
        ):
            raise NotificationEnrollmentError("notification_pagination_invalid")
        seen_tokens.add(next_token)
        token = next_token
    raise NotificationEnrollmentError("notification_pagination_exceeded")


def _verify_account(sts_client: StsClient, account_id: str) -> None:
    if sts_client.get_caller_identity().get("Account") != account_id:
        raise NotificationEnrollmentError("aws_account_mismatch")


def _confirmed_subscription_arn(value: object, topic_arn: str) -> bool:
    return bool(
        isinstance(value, str)
        and value.startswith(f"{topic_arn}:")
        and len(value) <= len(topic_arn) + 129
        and not any(ord(character) < 32 for character in value)
    )


def enroll_notifications(
    *,
    account_id: str,
    region: str,
    notification_email: str,
    sts_client: StsClient,
    sns_client: SnsClient,
) -> dict[str, Any]:
    """Idempotently enroll one SNS address without persisting or returning it."""

    _validate_identity(account_id, region)
    validated_email = _validate_email(notification_email, required=True)
    if validated_email is None:
        raise NotificationEnrollmentError("notification_address_missing")
    _verify_account(sts_client, account_id)

    topic_arn = f"arn:aws:sns:{region}:{account_id}:{TOPIC_NAME}"
    subscriptions = _sns_subscriptions(sns_client, topic_arn)
    if subscriptions:
        if (
            len(subscriptions) != 1
            or subscriptions[0].get("Protocol") != "email"
            or subscriptions[0].get("Endpoint") != validated_email
        ):
            raise NotificationEnrollmentError("notification_subscriber_conflict")
        subscription_arn = subscriptions[0].get("SubscriptionArn")
        if subscription_arn == "PendingConfirmation":
            action = "pending_confirmation"
        elif _confirmed_subscription_arn(subscription_arn, topic_arn):
            action = "unchanged_confirmed"
        else:
            raise NotificationEnrollmentError("notification_subscription_identity_invalid")
    else:
        sns_client.subscribe(
            TopicArn=topic_arn,
            Protocol="email",
            Endpoint=validated_email,
            ReturnSubscriptionArn=True,
        )
        action = "confirmation_requested"

    return {"notification_subscription": action, "status": "passed"}


def verify_notification_enrollment(
    *,
    account_id: str,
    region: str,
    sts_client: StsClient,
    sns_client: SnsClient,
) -> dict[str, Any]:
    """Require one confirmed SNS email subscriber and emit value-free evidence."""

    _validate_identity(account_id, region)
    _verify_account(sts_client, account_id)
    topic_arn = f"arn:aws:sns:{region}:{account_id}:{TOPIC_NAME}"
    subscriptions = _sns_subscriptions(sns_client, topic_arn)
    if len(subscriptions) != 1 or subscriptions[0].get("Protocol") != "email":
        raise NotificationEnrollmentError("notification_subscriber_count_invalid")
    endpoint = subscriptions[0].get("Endpoint")
    if not isinstance(endpoint, str) or _validate_email(endpoint, required=True) is None:
        raise NotificationEnrollmentError("notification_subscriber_invalid")
    subscription_arn = subscriptions[0].get("SubscriptionArn")
    if subscription_arn == "PendingConfirmation":
        raise NotificationEnrollmentError("notification_subscription_unconfirmed")
    if not _confirmed_subscription_arn(subscription_arn, topic_arn):
        raise NotificationEnrollmentError("notification_subscription_identity_invalid")
    return {"notification_subscribers_confirmed": 1, "status": "passed"}


def _clients(region: str, profile: str | None = None) -> tuple[StsClient, SnsClient, str | None]:
    config = Config(
        connect_timeout=5,
        read_timeout=15,
        retries={"max_attempts": 3, "mode": "standard"},
        user_agent_extra="modelguard-notification-enrollment/1",
    )
    session = boto3.Session(profile_name=profile, region_name=region)
    credentials = session.get_credentials()
    method = None if credentials is None else credentials.method
    return (
        cast(StsClient, session.client("sts", region_name=region, config=config)),
        cast(SnsClient, session.client("sns", region_name=region, config=config)),
        method,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="notification-enrollment")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("enroll", "verify"):
        item = subparsers.add_parser(command)
        item.add_argument("--account-id", required=True)
        item.add_argument("--region", required=True)
    subparsers.choices["enroll"].add_argument("--confirmation", required=True)
    subparsers.choices["enroll"].add_argument(
        "--profile", choices=(APPROVED_PROFILE,), required=True
    )
    subparsers.choices["verify"].add_argument("--workflow-role-arn", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        profile = args.profile if args.command == "enroll" else None
        if args.command == "enroll":
            if os.environ.get("GITHUB_ACTIONS", "").casefold() == "true":
                raise NotificationEnrollmentError("workflow_enrollment_forbidden")
            if args.confirmation != ENROLL_CONFIRMATION:
                raise NotificationEnrollmentError("enrollment_confirmation_invalid")
            if not sys.stdin.isatty():
                raise NotificationEnrollmentError("interactive_terminal_required")
        sts_client, sns_client, credential_method = _clients(args.region, profile)
        if args.command == "enroll":
            identity = sts_client.get_caller_identity()
            verify_human_login_identity(
                profile=args.profile,
                region=args.region,
                expected_account_id=args.account_id,
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
            notification_email = getpass.getpass("Drift and alarm notification email: ")
            result = enroll_notifications(
                account_id=args.account_id,
                region=args.region,
                notification_email=notification_email,
                sts_client=sts_client,
                sns_client=sns_client,
            )
        else:
            identity = sts_client.get_caller_identity()
            account_id = identity.get("Account")
            if not isinstance(account_id, str) or account_id != args.account_id:
                raise NotificationEnrollmentError("aws_account_mismatch")
            verify_workflow_oidc_identity(
                expected_account_id=args.account_id,
                expected_role_arn=args.workflow_role_arn,
                credential_method=credential_method,
                identity=identity,
            )
            result = verify_notification_enrollment(
                account_id=args.account_id,
                region=args.region,
                sts_client=sts_client,
                sns_client=sns_client,
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (HumanLoginRefusal, NotificationEnrollmentError) as error:
        print(json.dumps({"reason": str(error), "status": "refused"}), file=sys.stderr)
        return 2
    except (BotoCoreError, ClientError):
        print(
            json.dumps({"reason": "notification_aws_operation_failed", "status": "refused"}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
