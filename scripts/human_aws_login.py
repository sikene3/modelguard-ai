#!/usr/bin/env python3
"""Fail-closed identity guard for browser-authenticated human AWS operations."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import re
import sys
from collections.abc import Mapping
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

APPROVED_PROFILE = "modelguard-bootstrap"
APPROVED_REGION = "us-east-1"
APPROVED_USER = "modelguard-bootstrap-admin"
APPROVED_AWSCRT_VERSION = "0.36.0"
AWSCRT_REQUIREMENT_PATTERN = re.compile(r"^awscrt \(==([0-9]+(?:\.[0-9]+)+)\)")


class HumanLoginRefusal(RuntimeError):
    """The caller is not the exact temporary browser-login identity."""


def verify_browser_login_dependency() -> dict[str, str]:
    """Prove the locally installed CRT exactly satisfies Botocore's login-provider extra."""

    try:
        botocore_version = importlib.metadata.version("botocore")
        awscrt_version = importlib.metadata.version("awscrt")
        requirements = importlib.metadata.metadata("botocore").get_all("Requires-Dist") or []
        importlib.import_module("awscrt")
    except (ImportError, importlib.metadata.PackageNotFoundError) as error:
        raise HumanLoginRefusal("browser_login_dependency_missing") from error

    required_versions = {
        match.group(1)
        for requirement in requirements
        if (match := AWSCRT_REQUIREMENT_PATTERN.match(requirement)) is not None
    }
    if required_versions != {APPROVED_AWSCRT_VERSION}:
        raise HumanLoginRefusal("botocore_login_dependency_contract_mismatch")
    if awscrt_version != APPROVED_AWSCRT_VERSION:
        raise HumanLoginRefusal("browser_login_dependency_version_mismatch")
    return {
        "awscrt_version": awscrt_version,
        "botocore_version": botocore_version,
        "status": "passed",
    }


def verify_workflow_oidc_identity(
    *,
    expected_account_id: str,
    expected_role_arn: str,
    credential_method: str | None,
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Require the exact deploy-role session injected by the OIDC credentials action."""

    if re.fullmatch(r"[0-9]{12}", expected_account_id) is None:
        raise HumanLoginRefusal("expected_account_invalid")
    required_role_arn = (
        f"arn:aws:iam::{expected_account_id}:role/modelguard-ai/bootstrap/modelguard-ai-ci-deploy"
    )
    if expected_role_arn != required_role_arn:
        raise HumanLoginRefusal("workflow_role_identity_invalid")
    if credential_method != "env":
        raise HumanLoginRefusal("workflow_temporary_credentials_required")
    if identity.get("Account") != expected_account_id:
        raise HumanLoginRefusal("workflow_account_identity_invalid")
    arn = identity.get("Arn")
    prefix = f"arn:aws:sts::{expected_account_id}:assumed-role/modelguard-ai-ci-deploy/"
    if (
        not isinstance(arn, str)
        or not arn.startswith(prefix)
        or re.fullmatch(r"[A-Za-z0-9+=,.@_-]{2,64}", arn.removeprefix(prefix)) is None
    ):
        raise HumanLoginRefusal("workflow_oidc_session_required")
    return {
        "account_id_masked": f"********{expected_account_id[-4:]}",
        "credential_source": "github_oidc_temporary_session",
        "role": "modelguard-ai-ci-deploy",
        "status": "passed",
    }


def verify_human_login_identity(
    *,
    profile: str,
    region: str,
    expected_account_id: str,
    credential_method: str | None,
    identity: Mapping[str, Any],
    environment_credential_names: set[str] | None = None,
) -> dict[str, Any]:
    """Verify only metadata; never return or log credential material."""

    if profile != APPROVED_PROFILE:
        raise HumanLoginRefusal("approved_profile_required")
    if region != APPROVED_REGION:
        raise HumanLoginRefusal("canonical_region_required")
    if re.fullmatch(r"[0-9]{12}", expected_account_id) is None:
        raise HumanLoginRefusal("expected_account_invalid")
    if environment_credential_names:
        raise HumanLoginRefusal("environment_credentials_forbidden")
    if credential_method != "login":
        raise HumanLoginRefusal("browser_login_credentials_required")
    account = identity.get("Account")
    arn = identity.get("Arn")
    expected_arn = f"arn:aws:iam::{expected_account_id}:user/{APPROVED_USER}"
    if account != expected_account_id or arn != expected_arn:
        raise HumanLoginRefusal("non_root_bootstrap_user_required")
    return {
        "account_id_masked": f"********{expected_account_id[-4:]}",
        "credential_source": "temporary_browser_login",
        "identity": APPROVED_USER,
        "profile": APPROVED_PROFILE,
        "region": APPROVED_REGION,
        "status": "passed",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="human-aws-login")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "dependency",
        help="locally verify the pinned Botocore browser-login dependency without AWS access",
    )
    verify = subparsers.add_parser("verify")
    verify.add_argument("--profile", required=True)
    verify.add_argument("--region", required=True)
    verify.add_argument("--expected-account-id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "dependency":
        try:
            result = verify_browser_login_dependency()
        except HumanLoginRefusal as error:
            print(json.dumps({"reason": str(error), "status": "refused"}), file=sys.stderr)
            return 2
        print(json.dumps(result, sort_keys=True))
        return 0

    credential_environment = {
        name
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
        if name in os.environ
    }
    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        credentials = session.get_credentials()
        method = None if credentials is None else credentials.method
        identity = session.client("sts", region_name=args.region).get_caller_identity()
        result = verify_human_login_identity(
            profile=args.profile,
            region=args.region,
            expected_account_id=args.expected_account_id,
            credential_method=method,
            identity=identity,
            environment_credential_names=credential_environment,
        )
    except HumanLoginRefusal as error:
        print(json.dumps({"reason": str(error), "status": "refused"}), file=sys.stderr)
        return 2
    except (BotoCoreError, ClientError, RuntimeError):
        print(
            json.dumps({"reason": "browser_login_verification_failed", "status": "refused"}),
            file=sys.stderr,
        )
        return 3
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
