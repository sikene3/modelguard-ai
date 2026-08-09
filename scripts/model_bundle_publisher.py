#!/usr/bin/env python3
"""Credential-safe entry point for create-only model publication and pointer promotion."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, cast

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from modelguard.storage.publisher import (
    CANONICAL_REGION,
    CreateOnlyModelBundlePublisher,
    ModelObjectClient,
    ModelPointerClient,
    ModelPublicationError,
)
from modelguard.storage.versioned_bundle import verify_model_joblib_memory_bound
from modelguard.training.bundle import inspect_bundle
from scripts.human_aws_login import (
    APPROVED_PROFILE,
    HumanLoginRefusal,
    verify_browser_login_dependency,
    verify_human_login_identity,
    verify_workflow_oidc_identity,
)

PUBLISH_CONFIRMATION = "PUBLISH AND PROMOTE modelguard-ai model"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="model-bundle-publisher")
    parser.add_argument("publish-and-promote", choices=("publish-and-promote",))
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--region", choices=(CANONICAL_REGION,), required=True)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--profile", choices=(APPROVED_PROFILE,))
    identity.add_argument("--workflow-role-arn")
    parser.add_argument("--confirmation", required=True)
    return parser


def _environment_credential_names() -> set[str]:
    return {
        name
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
        if name in os.environ
    }


def _safe_refusal(reason: str) -> int:
    print(json.dumps({"reason": reason, "status": "refused"}, sort_keys=True), file=sys.stderr)
    return 2


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.confirmation != PUBLISH_CONFIRMATION:
        return _safe_refusal("publication_confirmation_invalid")
    try:
        verify_browser_login_dependency()
        try:
            metadata = inspect_bundle(arguments.bundle)
            verify_model_joblib_memory_bound(arguments.bundle / "model.joblib")
            if arguments.bundle.name != metadata.identity.model_version:
                raise ValueError("bundle directory name differs from its semantic version")
        except (OSError, ValueError) as error:
            raise ModelPublicationError("local_bundle_verification_failed") from error
        config = Config(
            connect_timeout=2.0,
            read_timeout=10.0,
            retries={"max_attempts": 3, "mode": "standard"},
            user_agent_extra="modelguard-model-publisher/1",
        )
        session = boto3.Session(
            profile_name=arguments.profile,
            region_name=arguments.region,
        )
        credentials = session.get_credentials()
        credential_method = None if credentials is None else credentials.method
        sts = session.client("sts", region_name=arguments.region, config=config)
        identity: dict[str, Any] = sts.get_caller_identity()
        if arguments.profile is not None:
            verify_human_login_identity(
                profile=arguments.profile,
                region=arguments.region,
                expected_account_id=arguments.expected_account_id,
                credential_method=credential_method,
                identity=identity,
                environment_credential_names=_environment_credential_names(),
            )
        else:
            if os.environ.get("GITHUB_ACTIONS") != "true":
                raise HumanLoginRefusal("workflow_oidc_context_required")
            verify_workflow_oidc_identity(
                expected_account_id=arguments.expected_account_id,
                expected_role_arn=arguments.workflow_role_arn,
                credential_method=credential_method,
                identity=identity,
            )
        bucket = f"modelguard-ai-demo-{arguments.expected_account_id}-{arguments.region}-models"
        publisher = CreateOnlyModelBundlePublisher(
            s3_client=cast(
                ModelObjectClient,
                session.client("s3", region_name=arguments.region, config=config),
            ),
            ssm_client=cast(
                ModelPointerClient,
                session.client("ssm", region_name=arguments.region, config=config),
            ),
            bucket=bucket,
            expected_account_id=arguments.expected_account_id,
            region=arguments.region,
        )
        result = publisher.publish_and_promote(arguments.bundle)
    except (HumanLoginRefusal, ModelPublicationError) as error:
        reason = error.reason if isinstance(error, ModelPublicationError) else str(error)
        return _safe_refusal(reason)
    except (BotoCoreError, ClientError, OSError, ValueError):
        return _safe_refusal("model_publication_failed")
    except KeyboardInterrupt:
        return _safe_refusal("model_publication_interrupted")
    print(json.dumps(result.model_dump(mode="json", exclude_none=True), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
