#!/usr/bin/env python3
"""Fail-closed local contract for team-protected and solo-portfolio deployments."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from typing import Literal

GovernanceMode = Literal["team_protected", "solo_portfolio"]
Operation = Literal["plan", "publish", "deploy", "activation", "rollback", "destroy"]
ReviewStage = Literal["prerequisites", "activation", "destroy"]

REPOSITORY = "sikene3/modelguard-ai"
MAIN_REF = "refs/heads/main"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(
    r"^[0-9]{12}\.dkr\.ecr\.us-east-1\.amazonaws\.com/"
    r"modelguard-ai/demo/(api|dashboard|monitor)@sha256:[0-9a-f]{64}$"
)


class GovernanceRefusal(ValueError):
    """A deployment-governance input did not match the immutable contract."""


@dataclass(frozen=True)
class EntryContract:
    mode: GovernanceMode
    operation: Operation
    repository: str
    repository_visibility: str
    event_name: str
    git_ref: str
    environment: str
    workflow_ref: str
    job_workflow_ref: str
    source_commit: str
    workflow_commit: str
    job_workflow_commit: str
    confirmation: str | None = None


def _operation_contract(operation: Operation) -> tuple[str, str, set[str]]:
    if operation == "plan":
        return (
            "demo-plan",
            ".github/workflows/terraform-plan.yml",
            {
                "push",
                "workflow_dispatch",
            },
        )
    if operation == "publish":
        return (
            "demo",
            ".github/workflows/publish-images.yml",
            {
                "workflow_call",
                "workflow_dispatch",
            },
        )
    if operation in {"deploy", "activation"}:
        return "demo", ".github/workflows/deploy-demo.yml", {"workflow_dispatch"}
    if operation == "rollback":
        return "demo", ".github/workflows/rollback-demo.yml", {"workflow_dispatch"}
    if operation == "destroy":
        return "demo-destroy", ".github/workflows/destroy-demo.yml", {"workflow_dispatch"}
    raise GovernanceRefusal("operation_invalid")


def _expected_confirmation(mode: GovernanceMode, operation: Operation) -> str | None:
    if operation == "plan":
        return None
    if operation == "publish":
        return "PUBLISH modelguard-ai images"
    if operation in {"deploy", "activation"}:
        return "DEPLOY modelguard-ai demo"
    if operation == "rollback":
        return (
            "ROLLBACK SOLO modelguard-ai demo"
            if mode == "solo_portfolio"
            else "ROLLBACK TEAM modelguard-ai demo"
        )
    if mode == "solo_portfolio":
        return "DESTROY SOLO modelguard-ai demo"
    return "DESTROY TEAM modelguard-ai demo"


def verify_entry(contract: EntryContract) -> dict[str, str]:
    if contract.mode not in {"team_protected", "solo_portfolio"}:
        raise GovernanceRefusal("governance_mode_invalid")
    if contract.operation not in {"plan", "publish", "deploy", "activation", "rollback", "destroy"}:
        raise GovernanceRefusal("operation_invalid")
    if contract.repository != REPOSITORY:
        raise GovernanceRefusal("repository_identity_mismatch")
    expected_visibility = "public" if contract.mode == "solo_portfolio" else "private"
    if contract.repository_visibility != expected_visibility:
        raise GovernanceRefusal("repository_visibility_mismatch")
    if contract.mode == "solo_portfolio" and contract.event_name != "workflow_dispatch":
        raise GovernanceRefusal("solo_privileged_entry_not_manual")
    if contract.git_ref != MAIN_REF:
        raise GovernanceRefusal("git_ref_mismatch")
    if SHA_PATTERN.fullmatch(contract.source_commit) is None:
        raise GovernanceRefusal("source_commit_invalid")
    if not (contract.source_commit == contract.workflow_commit == contract.job_workflow_commit):
        raise GovernanceRefusal("source_commit_mismatch")
    environment, path, allowed_events = _operation_contract(contract.operation)
    if contract.environment != environment:
        raise GovernanceRefusal("environment_mismatch")
    if contract.event_name not in allowed_events:
        raise GovernanceRefusal("event_not_manual_or_trusted")
    expected_job_workflow_ref = f"{REPOSITORY}/{path}@{MAIN_REF}"
    expected_workflow_ref = expected_job_workflow_ref
    if contract.operation == "publish" and contract.event_name == "workflow_call":
        expected_workflow_ref = f"{REPOSITORY}/.github/workflows/deploy-demo.yml@{MAIN_REF}"
    if contract.workflow_ref != expected_workflow_ref:
        raise GovernanceRefusal("workflow_identity_mismatch")
    if contract.job_workflow_ref != expected_job_workflow_ref:
        raise GovernanceRefusal("job_workflow_identity_mismatch")
    expected_confirmation = _expected_confirmation(contract.mode, contract.operation)
    if contract.confirmation != expected_confirmation:
        raise GovernanceRefusal("typed_confirmation_mismatch")
    return {
        "governance_mode": contract.mode,
        "operation": contract.operation,
        "status": "passed",
    }


def verify_release_evidence(
    *,
    source_commit: str,
    workflow_commit: str,
    governance_mode: GovernanceMode,
    stage: ReviewStage,
    run_identity: str,
    reviewed_run_identity: str,
    confirmation: str,
    image_refs: tuple[str, str, str] | None,
    reviewed_image_refs: tuple[str, str, str] | None,
    model_pointer_sha256: str | None,
    reviewed_model_pointer_sha256: str | None,
    plan_sha256: str,
    reviewed_plan_sha256: str,
    plan_identity_sha256: str,
    reviewed_plan_identity_sha256: str,
) -> dict[str, str]:
    if SHA_PATTERN.fullmatch(source_commit) is None or source_commit != workflow_commit:
        raise GovernanceRefusal("source_commit_mismatch")
    if governance_mode not in {"team_protected", "solo_portfolio"}:
        raise GovernanceRefusal("governance_mode_invalid")
    if stage not in {"prerequisites", "activation", "destroy"}:
        raise GovernanceRefusal("review_stage_invalid")
    if re.fullmatch(rf"[1-9][0-9]*:[1-9][0-9]*:{stage}", run_identity) is None:
        raise GovernanceRefusal("review_run_identity_invalid")
    if run_identity != reviewed_run_identity:
        raise GovernanceRefusal("review_run_identity_mismatch")
    expected_confirmation = {
        ("team_protected", "prerequisites"): "APPLY TEAM modelguard-ai prerequisites",
        ("solo_portfolio", "prerequisites"): "APPLY SOLO modelguard-ai prerequisites",
        ("team_protected", "activation"): "ACTIVATE TEAM modelguard-ai demo",
        ("solo_portfolio", "activation"): "ACTIVATE SOLO modelguard-ai demo",
        ("team_protected", "destroy"): "DESTROY TEAM modelguard-ai demo",
        ("solo_portfolio", "destroy"): "DESTROY SOLO modelguard-ai demo",
    }[(governance_mode, stage)]
    if confirmation != expected_confirmation:
        raise GovernanceRefusal("review_confirmation_mismatch")
    if stage == "activation":
        if image_refs is None:
            raise GovernanceRefusal("immutable_image_digest_set_invalid")
        components = {
            match.group(1) for value in image_refs if (match := DIGEST_PATTERN.fullmatch(value))
        }
        if components != {"api", "dashboard", "monitor"}:
            raise GovernanceRefusal("immutable_image_digest_set_invalid")
        if image_refs != reviewed_image_refs:
            raise GovernanceRefusal("reviewed_image_digest_set_mismatch")
        if (
            model_pointer_sha256 is None
            or re.fullmatch(r"[0-9a-f]{64}", model_pointer_sha256) is None
        ):
            raise GovernanceRefusal("model_pointer_sha256_invalid")
        if model_pointer_sha256 != reviewed_model_pointer_sha256:
            raise GovernanceRefusal("reviewed_model_pointer_sha256_mismatch")
    elif (
        image_refs is not None
        or reviewed_image_refs is not None
        or model_pointer_sha256 is not None
        or reviewed_model_pointer_sha256 is not None
    ):
        raise GovernanceRefusal("stage_inapplicable_release_evidence")
    for value, category in (
        (plan_sha256, "plan_sha256_invalid"),
        (reviewed_plan_sha256, "reviewed_plan_sha256_invalid"),
        (plan_identity_sha256, "plan_identity_sha256_invalid"),
        (reviewed_plan_identity_sha256, "reviewed_plan_identity_sha256_invalid"),
    ):
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise GovernanceRefusal(category)
    if plan_sha256 != reviewed_plan_sha256:
        raise GovernanceRefusal("saved_plan_hash_mismatch")
    if plan_identity_sha256 != reviewed_plan_identity_sha256:
        raise GovernanceRefusal("saved_plan_identity_mismatch")
    return {
        "governance_mode": governance_mode,
        "run_identity": run_identity,
        "stage": stage,
        "status": "passed",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deployment-governance")
    subparsers = parser.add_subparsers(dest="command", required=True)
    entry = subparsers.add_parser("entry")
    entry.add_argument("--mode", choices=("team_protected", "solo_portfolio"), required=True)
    entry.add_argument(
        "--operation",
        choices=("plan", "publish", "deploy", "activation", "rollback", "destroy"),
        required=True,
    )
    entry.add_argument("--repository", required=True)
    entry.add_argument("--repository-visibility", choices=("private", "public"), required=True)
    entry.add_argument("--event-name", required=True)
    entry.add_argument("--git-ref", required=True)
    entry.add_argument("--environment", required=True)
    entry.add_argument("--workflow-ref", required=True)
    entry.add_argument("--job-workflow-ref", required=True)
    entry.add_argument("--source-commit", required=True)
    entry.add_argument("--workflow-commit", required=True)
    entry.add_argument("--job-workflow-commit", required=True)
    entry.add_argument("--confirmation")
    evidence = subparsers.add_parser("evidence")
    evidence.add_argument("--mode", choices=("team_protected", "solo_portfolio"), required=True)
    evidence.add_argument(
        "--stage", choices=("prerequisites", "activation", "destroy"), required=True
    )
    evidence.add_argument("--run-identity", required=True)
    evidence.add_argument("--reviewed-run-identity", required=True)
    evidence.add_argument("--confirmation", required=True)
    evidence.add_argument("--source-commit", required=True)
    evidence.add_argument("--workflow-commit", required=True)
    evidence.add_argument("--api-image-ref")
    evidence.add_argument("--dashboard-image-ref")
    evidence.add_argument("--monitor-image-ref")
    evidence.add_argument("--reviewed-api-image-ref")
    evidence.add_argument("--reviewed-dashboard-image-ref")
    evidence.add_argument("--reviewed-monitor-image-ref")
    evidence.add_argument("--model-pointer-sha256")
    evidence.add_argument("--reviewed-model-pointer-sha256")
    evidence.add_argument("--plan-sha256", required=True)
    evidence.add_argument("--reviewed-plan-sha256", required=True)
    evidence.add_argument("--plan-identity-sha256", required=True)
    evidence.add_argument("--reviewed-plan-identity-sha256", required=True)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        if arguments.command == "entry":
            result = verify_entry(
                EntryContract(
                    mode=arguments.mode,
                    operation=arguments.operation,
                    repository=arguments.repository,
                    repository_visibility=arguments.repository_visibility,
                    event_name=arguments.event_name,
                    git_ref=arguments.git_ref,
                    environment=arguments.environment,
                    workflow_ref=arguments.workflow_ref,
                    job_workflow_ref=arguments.job_workflow_ref,
                    source_commit=arguments.source_commit,
                    workflow_commit=arguments.workflow_commit,
                    job_workflow_commit=arguments.job_workflow_commit,
                    confirmation=arguments.confirmation,
                )
            )
        else:
            result = verify_release_evidence(
                governance_mode=arguments.mode,
                stage=arguments.stage,
                run_identity=arguments.run_identity,
                reviewed_run_identity=arguments.reviewed_run_identity,
                confirmation=arguments.confirmation,
                source_commit=arguments.source_commit,
                workflow_commit=arguments.workflow_commit,
                image_refs=(
                    (
                        arguments.api_image_ref,
                        arguments.dashboard_image_ref,
                        arguments.monitor_image_ref,
                    )
                    if all(
                        value is not None
                        for value in (
                            arguments.api_image_ref,
                            arguments.dashboard_image_ref,
                            arguments.monitor_image_ref,
                        )
                    )
                    else None
                ),
                reviewed_image_refs=(
                    (
                        arguments.reviewed_api_image_ref,
                        arguments.reviewed_dashboard_image_ref,
                        arguments.reviewed_monitor_image_ref,
                    )
                    if all(
                        value is not None
                        for value in (
                            arguments.reviewed_api_image_ref,
                            arguments.reviewed_dashboard_image_ref,
                            arguments.reviewed_monitor_image_ref,
                        )
                    )
                    else None
                ),
                model_pointer_sha256=arguments.model_pointer_sha256,
                reviewed_model_pointer_sha256=arguments.reviewed_model_pointer_sha256,
                plan_sha256=arguments.plan_sha256,
                reviewed_plan_sha256=arguments.reviewed_plan_sha256,
                plan_identity_sha256=arguments.plan_identity_sha256,
                reviewed_plan_identity_sha256=arguments.reviewed_plan_identity_sha256,
            )
    except GovernanceRefusal as error:
        print(json.dumps({"reason": str(error), "status": "refused"}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
