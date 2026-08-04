#!/usr/bin/env python3
"""Create and validate durable last-known-good deployment records."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from scripts.release_manifest import COMPONENTS, ImageReleaseManifest
from scripts.terraform_demo_guard import ActivePointer, PlanManifest


class DeploymentRecordError(RuntimeError):
    """A safe deployment-record refusal reason."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeploymentRecord(StrictModel):
    schema_version: Literal["modelguard.last-known-good.v1"]
    status: Literal["smoke_passed"]
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    github_repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    github_run_id: str = Field(pattern=r"^[0-9]+$")
    github_run_attempt: str = Field(pattern=r"^[0-9]+$")
    recorded_at: datetime
    aws_account_id: str = Field(pattern=r"^[0-9]{12}$")
    aws_region: str = Field(pattern=r"^[a-z]{2}(-[a-z]+)+-[0-9]+$")
    image_release_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_refs: dict[str, str]
    task_definitions: dict[str, str]
    active_model_pointer: ActivePointer
    plans: dict[str, str]
    smoke_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rollback_contract: dict[str, Any]

    @model_validator(mode="after")
    def exact_runtime_identity(self) -> DeploymentRecord:
        if self.recorded_at.utcoffset() != timedelta(0):
            raise ValueError("recorded_at must be UTC")
        if set(self.image_refs) != set(COMPONENTS) or set(self.task_definitions) != set(COMPONENTS):
            raise ValueError("record must contain all three image/task-definition identities")
        for component, image_ref in self.image_refs.items():
            expected_prefix = (
                f"{self.aws_account_id}.dkr.ecr.{self.aws_region}.amazonaws.com/"
                f"modelguard-ai/demo/{component}@sha256:"
            )
            if (
                not image_ref.startswith(expected_prefix)
                or re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image_ref) is None
            ):
                raise ValueError("record image reference is not exact")
        for component, task_definition in self.task_definitions.items():
            pattern = (
                rf"^arn:aws:ecs:{re.escape(self.aws_region)}:{self.aws_account_id}:"
                rf"task-definition/modelguard-ai-demo-{component}:[0-9]+$"
            )
            if re.fullmatch(pattern, task_definition) is None:
                raise ValueError("record task-definition identity is not exact")
        expected_model_bucket = f"modelguard-ai-demo-{self.aws_account_id}-{self.aws_region}-models"
        if self.active_model_pointer.bundle.get("bucket") != expected_model_bucket:
            raise ValueError("record active model bucket is not exact")
        if set(self.plans) != {"prerequisites", "activation"} or not all(
            re.fullmatch(r"[0-9a-f]{64}", value) for value in self.plans.values()
        ):
            raise ValueError("record must bind both reviewed plan hashes")
        expected_rollback = {
            "ecs": (
                "automatic circuit breaker plus explicit last-known-good service task definitions"
            ),
            "model": "separate protected pointer operation; never automatic from drift",
            "drift_triggers_rollback": False,
        }
        if self.rollback_contract != expected_rollback:
            raise ValueError("record rollback contract is not the approved exact policy")
        return self


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_object(path: Path) -> dict[str, Any]:
    value = _load_json(path)
    if not isinstance(value, dict):
        raise DeploymentRecordError("json_root_not_object")
    return value


def _pointer_from_response(path: Path) -> ActivePointer:
    response = _load_object(path)
    parameter = response.get("Parameter")
    if not isinstance(parameter, dict):
        raise DeploymentRecordError("deployment_record_live_pointer_missing")
    if (
        parameter.get("Name") != "/modelguard-ai/demo/models/active"
        or parameter.get("Type") != "String"
        or not isinstance(parameter.get("Value"), str)
    ):
        raise DeploymentRecordError("deployment_record_live_pointer_identity_invalid")
    value = json.loads(parameter["Value"])
    if not isinstance(value, dict):
        raise DeploymentRecordError("deployment_record_live_pointer_value_invalid")
    return ActivePointer.model_validate(value)


def create_record(
    *,
    image_manifest_path: Path,
    pointer_path: Path,
    live_pointer_response_path: Path,
    task_definitions_path: Path,
    deployed_images_path: Path,
    prerequisite_manifest_path: Path,
    activation_manifest_path: Path,
    smoke_summary_path: Path,
    github_repository: str,
    github_run_id: str,
    github_run_attempt: str,
    now: datetime | None = None,
) -> DeploymentRecord:
    """Bind the successful smoke result to all independent rollback targets."""

    image_manifest = ImageReleaseManifest.model_validate(_load_object(image_manifest_path))
    pointer = ActivePointer.model_validate(_load_object(pointer_path))
    live_pointer = _pointer_from_response(live_pointer_response_path)
    if live_pointer != pointer:
        raise DeploymentRecordError("deployment_record_live_pointer_mismatch")
    task_definitions = _load_object(task_definitions_path)
    deployed_images = _load_object(deployed_images_path)
    prerequisite = PlanManifest.model_validate(_load_object(prerequisite_manifest_path))
    activation = PlanManifest.model_validate(_load_object(activation_manifest_path))
    smoke = _load_object(smoke_summary_path)
    if (
        smoke.get("schema_version") != "modelguard.aws-smoke-evidence.v1"
        or smoke.get("status") != "passed"
        or smoke.get("checks") != ["live", "ready", "version", "prediction"]
    ):
        raise DeploymentRecordError("deployment_record_requires_passed_smoke")
    if smoke.get("model_version") != pointer.target_identity.get("model_version") or smoke.get(
        "model_manifest_sha256"
    ) != pointer.target_identity.get("bundle_manifest_sha256"):
        raise DeploymentRecordError("deployment_record_smoke_model_mismatch")
    expected_images = {
        component: image.image_ref for component, image in image_manifest.images.items()
    }
    if deployed_images != expected_images:
        raise DeploymentRecordError("deployment_record_deployed_image_mismatch")
    if prerequisite.stage != "prerequisites" or activation.stage != "activation":
        raise DeploymentRecordError("deployment_record_plan_stage_mismatch")
    if prerequisite.git_commit != activation.git_commit or (
        prerequisite.git_commit != image_manifest.source_commit
    ):
        raise DeploymentRecordError("deployment_record_source_commit_mismatch")
    if prerequisite.account_id != activation.account_id or (
        activation.account_id != image_manifest.aws_account_id
    ):
        raise DeploymentRecordError("deployment_record_account_mismatch")
    if prerequisite.region != activation.region or activation.region != image_manifest.aws_region:
        raise DeploymentRecordError("deployment_record_region_mismatch")
    return DeploymentRecord(
        schema_version="modelguard.last-known-good.v1",
        status="smoke_passed",
        source_commit=image_manifest.source_commit,
        github_repository=github_repository,
        github_run_id=github_run_id,
        github_run_attempt=github_run_attempt,
        recorded_at=now or datetime.now(tz=UTC),
        aws_account_id=image_manifest.aws_account_id,
        aws_region=image_manifest.aws_region,
        image_release_manifest_sha256=_sha256(image_manifest_path),
        image_refs={name: image.image_ref for name, image in image_manifest.images.items()},
        task_definitions={str(key): str(value) for key, value in task_definitions.items()},
        active_model_pointer=pointer,
        plans={
            "prerequisites": prerequisite.plan_sha256,
            "activation": activation.plan_sha256,
        },
        smoke_evidence_sha256=_sha256(smoke_summary_path),
        rollback_contract={
            "ecs": (
                "automatic circuit breaker plus explicit last-known-good service task definitions"
            ),
            "model": "separate protected pointer operation; never automatic from drift",
            "drift_triggers_rollback": False,
        },
    )


def _write_record(path: Path, record: DeploymentRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _append_rollback_outputs(path: Path, record: DeploymentRecord) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"api_task_definition={record.task_definitions['api']}\n")
        handle.write(f"dashboard_task_definition={record.task_definitions['dashboard']}\n")
        handle.write(f"monitor_task_definition={record.task_definitions['monitor']}\n")
        handle.write(
            f"model_version={record.active_model_pointer.target_identity['model_version']}\n"
        )
        handle.write(
            "model_manifest_sha256="
            f"{record.active_model_pointer.target_identity['bundle_manifest_sha256']}\n"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deployment-record")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--image-manifest", type=Path, required=True)
    create.add_argument("--pointer", type=Path, required=True)
    create.add_argument("--live-pointer-response", type=Path, required=True)
    create.add_argument("--task-definitions", type=Path, required=True)
    create.add_argument("--deployed-images", type=Path, required=True)
    create.add_argument("--prerequisite-manifest", type=Path, required=True)
    create.add_argument("--activation-manifest", type=Path, required=True)
    create.add_argument("--smoke-summary", type=Path, required=True)
    create.add_argument("--github-repository", required=True)
    create.add_argument("--github-run-id", required=True)
    create.add_argument("--github-run-attempt", required=True)
    create.add_argument("--output", type=Path, required=True)
    rollback = subparsers.add_parser("rollback-outputs")
    rollback.add_argument("--record", type=Path, required=True)
    rollback.add_argument("--github-output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "create":
            record = create_record(
                image_manifest_path=args.image_manifest,
                pointer_path=args.pointer,
                live_pointer_response_path=args.live_pointer_response,
                task_definitions_path=args.task_definitions,
                deployed_images_path=args.deployed_images,
                prerequisite_manifest_path=args.prerequisite_manifest,
                activation_manifest_path=args.activation_manifest,
                smoke_summary_path=args.smoke_summary,
                github_repository=args.github_repository,
                github_run_id=args.github_run_id,
                github_run_attempt=args.github_run_attempt,
            )
            _write_record(args.output, record)
        else:
            record = DeploymentRecord.model_validate(_load_object(args.record))
            _append_rollback_outputs(args.github_output, record)
        print(json.dumps({"status": "passed", "command": args.command}))
        return 0
    except (OSError, json.JSONDecodeError, ValidationError, DeploymentRecordError) as error:
        reason = str(error).splitlines()[0][:180]
        print(json.dumps({"status": "refused", "reason": reason}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
