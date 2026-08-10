#!/usr/bin/env python3
"""Pure Phase 08 deployment guards; no AWS or Terraform mutation is performed here."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import stat

# Subprocess is limited to the fixed local Git identity command in _git_commit.
import subprocess  # nosec B404
import sys
import tempfile
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from modelguard.core.serialization import parse_strict_json_bytes

SCHEMA_VERSION: Literal["modelguard.saved-plan-identity.v2"] = "modelguard.saved-plan-identity.v2"
PROJECT: Literal["modelguard-ai"] = "modelguard-ai"
ENVIRONMENT: Literal["demo"] = "demo"
BACKEND_KEY: Literal["modelguard-ai/demo/terraform.tfstate"] = (
    "modelguard-ai/demo/terraform.tfstate"
)
PLAN_NAMES = {
    "prerequisites": "prerequisites.tfplan",
    "activation": "activation.tfplan",
    "destroy": "destroy.tfplan",
}
IMAGE_PATTERN = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
TOKEN_ARN_PATTERN = re.compile(
    r"^arn:[^:]+:ssm:[a-z0-9-]+:[0-9]{12}:"
    r"parameter/modelguard-ai/demo/secrets/[A-Za-z0-9_./-]+$"
)
MODEL_BUNDLE_FILENAMES = {
    "baseline_profile.json",
    "checksums.sha256",
    "input_schema.json",
    "manifest.json",
    "metrics.json",
    "model.joblib",
    "threshold.json",
}
MAX_SAVED_PLAN_AGE = timedelta(hours=24)
MAX_SAVED_PLAN_CLOCK_SKEW = timedelta(minutes=5)
MAX_RENDERED_TFVARS_BYTES = 256 * 1024
MAX_TERRAFORM_STATE_BYTES = 32 * 1024 * 1024
type SourceActivationState = Literal["active", "dormant", "mixed_or_partial"]
RENDERED_TFVARS_COMMON_FIELDS = frozenset(
    {
        "activate_services",
        "alert_kms_key_arn",
        "alb_allowed_cidr",
        "api_access_mode",
        "auto_destroy_date",
        "availability_zones",
        "aws_account_id",
        "aws_region",
        "backend_bucket_name",
        "budget_prerequisite_verified",
        "deployment_governance_mode",
        "deployment_stage",
        "owner_tag",
        "permission_boundary_arn",
        "runtime_contract_verified",
        "teardown_authorized",
    }
)
RENDERED_TFVARS_HTTPS_FIELDS = frozenset({"acm_certificate_arn", "prediction_token_ssm_arn"})
RENDERED_TFVARS_ACTIVATION_FIELDS = frozenset(
    {
        "api_image_ref",
        "dashboard_image_ref",
        "expected_model_manifest_sha256",
        "expected_model_object_version_ids",
        "expected_model_version",
        "monitor_image_ref",
    }
)
POST_DESTROY_INVENTORY_SCHEMA_VERSION = "modelguard.post-destroy-inventory.v2"
POST_DESTROY_RESULT_CATEGORIES = (
    "residual_demo",
    "residual_service",
    "retained_bootstrap",
    "retained_budget",
    "validated_nonbillable",
    "unrelated",
)
POST_DESTROY_SERVICE_CATEGORIES = frozenset(
    {
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
)
POST_DESTROY_RETAINED_BUDGET = "modelguard-ai-demo-monthly"
POST_DESTROY_TASK_FAMILIES = ("api", "dashboard", "monitor")


def _expected_backend_bucket(account_id: str, region: str) -> str:
    return f"{PROJECT}-terraform-state-{account_id}-{region}"


def _expected_model_bucket(account_id: str, region: str) -> str:
    return f"{PROJECT}-{ENVIRONMENT}-{account_id}-{region}-models"


def _expected_image_prefix(account_id: str, region: str, component: str) -> str:
    return (
        f"{account_id}.dkr.ecr.{region}.amazonaws.com/{PROJECT}/{ENVIRONMENT}/{component}@sha256:"
    )


class GuardError(RuntimeError):
    """A bounded refusal reason safe to print in deployment evidence."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _safe_failure_reason(error: Exception, *, maximum: int = 200) -> str:
    if isinstance(error, OSError):
        return "local_io_failed"
    return str(error).splitlines()[0][:maximum]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_private_regular_file(path: Path, *, label: str) -> None:
    """Require an owner-only regular input without following a symlink."""

    try:
        metadata = path.lstat()
    except OSError as error:
        raise GuardError(f"{label}_unavailable") from error
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise GuardError(f"{label}_not_regular")
    if metadata.st_uid != os.geteuid():
        raise GuardError(f"{label}_owner_invalid")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise GuardError(f"{label}_mode_invalid")


def _strict_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise GuardError("rendered_tfvars_duplicate_key")
        value[key] = item
    return value


def _reject_json_constant(_: str) -> None:
    raise GuardError("rendered_tfvars_non_finite_number")


def _load_rendered_tfvars(path: Path) -> dict[str, Any]:
    _require_private_regular_file(path, label="rendered_tfvars")
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise GuardError("rendered_tfvars_unavailable") from error
    if not payload or len(payload) > MAX_RENDERED_TFVARS_BYTES:
        raise GuardError("rendered_tfvars_size_invalid")
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_strict_json_pairs,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GuardError("rendered_tfvars_json_invalid") from error
    if not isinstance(value, dict):
        raise GuardError("rendered_tfvars_root_not_object")
    return value


def _validate_rendered_tfvars(
    payload: dict[str, Any],
    *,
    stage: Literal["prerequisites", "activation", "destroy"],
    account_id: str,
    region: str,
    auto_destroy_date: date,
) -> None:
    """Require the exact stage-specific output contract of render_ci_terraform."""

    renderer_stage = "activation" if stage == "activation" else "prerequisites"
    activate_services = renderer_stage == "activation"
    teardown_authorized = stage == "destroy"
    access_mode = payload.get("api_access_mode")
    if not isinstance(access_mode, str) or access_mode not in {
        "http_cidr_only",
        "https_token",
    }:
        raise GuardError("rendered_tfvars_access_mode_invalid")
    expected_fields = set(RENDERED_TFVARS_COMMON_FIELDS)
    if access_mode == "https_token":
        expected_fields.update(RENDERED_TFVARS_HTTPS_FIELDS)
    if activate_services:
        expected_fields.update(RENDERED_TFVARS_ACTIVATION_FIELDS)
    if set(payload) != expected_fields:
        raise GuardError("rendered_tfvars_fields_mismatch")

    exact_values: dict[str, Any] = {
        "activate_services": activate_services,
        "auto_destroy_date": auto_destroy_date.isoformat(),
        "availability_zones": [f"{region}a", f"{region}b"],
        "aws_account_id": account_id,
        "aws_region": region,
        "backend_bucket_name": _expected_backend_bucket(account_id, region),
        "budget_prerequisite_verified": activate_services,
        "deployment_stage": renderer_stage,
        "runtime_contract_verified": activate_services,
        "teardown_authorized": teardown_authorized,
    }
    if any(payload.get(key) != expected for key, expected in exact_values.items()):
        raise GuardError("rendered_tfvars_stage_identity_mismatch")
    if not isinstance(payload.get("activate_services"), bool) or not isinstance(
        payload.get("runtime_contract_verified"), bool
    ):
        raise GuardError("rendered_tfvars_boolean_type_invalid")
    if not isinstance(payload.get("budget_prerequisite_verified"), bool) or not isinstance(
        payload.get("teardown_authorized"), bool
    ):
        raise GuardError("rendered_tfvars_boolean_type_invalid")

    owner_tag = payload.get("owner_tag")
    governance_mode = payload.get("deployment_governance_mode")
    if (
        not isinstance(owner_tag, str)
        or re.fullmatch(r"[A-Za-z0-9._-]{2,64}", owner_tag) is None
        or "@" in owner_tag
        or not isinstance(governance_mode, str)
        or governance_mode not in {"team_protected", "solo_portfolio"}
    ):
        raise GuardError("rendered_tfvars_governance_identity_invalid")
    expected_boundary = (
        f"arn:aws:iam::{account_id}:policy/{PROJECT}/bootstrap/{PROJECT}-workload-boundary"
    )
    alert_key = payload.get("alert_kms_key_arn")
    if payload.get("permission_boundary_arn") != expected_boundary or not isinstance(
        alert_key, str
    ):
        raise GuardError("rendered_tfvars_iam_or_kms_identity_invalid")
    if (
        re.fullmatch(
            rf"arn:aws:kms:{re.escape(region)}:{re.escape(account_id)}:"
            r"key/[0-9a-fA-F-]{36}",
            alert_key,
        )
        is None
    ):
        raise GuardError("rendered_tfvars_iam_or_kms_identity_invalid")
    cidr = payload.get("alb_allowed_cidr")
    if not isinstance(cidr, str):
        raise GuardError("rendered_tfvars_cidr_invalid")
    try:
        validate_restricted_cidr(cidr)
    except GuardError as error:
        raise GuardError("rendered_tfvars_cidr_invalid") from error

    if access_mode == "https_token":
        certificate = payload.get("acm_certificate_arn")
        token = payload.get("prediction_token_ssm_arn")
        if (
            not isinstance(certificate, str)
            or not certificate.startswith(f"arn:aws:acm:{region}:{account_id}:certificate/")
            or not isinstance(token, str)
            or TOKEN_ARN_PATTERN.fullmatch(token) is None
            or not token.startswith(
                f"arn:aws:ssm:{region}:{account_id}:parameter/{PROJECT}/{ENVIRONMENT}/secrets/"
            )
        ):
            raise GuardError("rendered_tfvars_https_identity_invalid")

    if activate_services:
        for component in ("api", "dashboard", "monitor"):
            image_ref = payload.get(f"{component}_image_ref")
            if (
                not isinstance(image_ref, str)
                or IMAGE_PATTERN.fullmatch(image_ref) is None
                or not image_ref.startswith(_expected_image_prefix(account_id, region, component))
            ):
                raise GuardError("rendered_tfvars_activation_image_invalid")
        model_version = payload.get("expected_model_version")
        manifest_sha = payload.get("expected_model_manifest_sha256")
        version_ids = payload.get("expected_model_object_version_ids")
        if (
            not isinstance(model_version, str)
            or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", model_version) is None
            or not isinstance(manifest_sha, str)
            or re.fullmatch(r"[0-9a-f]{64}", manifest_sha) is None
            or not isinstance(version_ids, dict)
            or set(version_ids) != MODEL_BUNDLE_FILENAMES
            or not all(
                isinstance(version_id, str)
                and 1 <= len(version_id) <= 1024
                and not any(ord(character) < 32 for character in version_id)
                for version_id in version_ids.values()
            )
        ):
            raise GuardError("rendered_tfvars_activation_pointer_invalid")


def _git(repository: Path, *arguments: str, failure: str) -> bytes:
    """Run one fixed local Git query without exposing its output on failure."""

    try:
        result = subprocess.run(  # nosec B603, B607
            ["git", *arguments],
            cwd=repository,
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise GuardError(failure) from error
    if result.returncode != 0:
        raise GuardError(failure)
    return result.stdout


def _git_commit(repository: Path) -> str:
    commit_bytes = _git(repository, "rev-parse", "HEAD", failure="git_commit_query_failed")
    try:
        commit = commit_bytes.decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise GuardError("git_commit_invalid") from error
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise GuardError("git_commit_invalid")
    return commit


def _verify_clean_repository(repository: Path) -> None:
    """Require no tracked or untracked source changes; standard ignored files stay ignored."""

    status = _git(
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignored=no",
        failure="git_status_query_failed",
    )
    if status:
        raise GuardError("git_source_tree_not_clean")


def validate_restricted_cidr(value: str) -> str:
    """Return one canonical restricted IPv4 CIDR or refuse it."""

    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError as error:
        raise GuardError("alb_cidr_not_canonical") from error
    if network.version != 4:
        raise GuardError("alb_cidr_ipv6_not_enabled")
    if network.prefixlen == 0:
        raise GuardError("alb_cidr_world_forbidden")
    return str(network)


class ActivePointer(StrictModel):
    pointer_schema_version: Literal["modelguard.active-monitor-target.v1"]
    target_identity: dict[str, Any]
    bundle: dict[str, Any]

    @model_validator(mode="after")
    def exact_identity(self) -> ActivePointer:
        if set(self.target_identity) != {
            "event_schema_version",
            "model_version",
            "bundle_manifest_sha256",
            "input_schema_version",
        }:
            raise ValueError("pointer target identity fields must be exact")
        if (
            self.target_identity.get("event_schema_version") != "modelguard.prediction-event.v1"
            or self.target_identity.get("input_schema_version") != "modelguard.input.v1"
        ):
            raise ValueError("pointer event and input schema versions must be exact")
        if set(self.bundle) != {"bucket", "key_prefix", "object_version_ids"}:
            raise ValueError("pointer bundle fields must be exact")
        bucket = self.bundle.get("bucket")
        if (
            not isinstance(bucket, str)
            or re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket) is None
        ):
            raise ValueError("pointer bucket name is invalid")
        version = self.target_identity.get("model_version")
        digest = self.target_identity.get("bundle_manifest_sha256")
        if not isinstance(version, str) or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
            raise ValueError("pointer model_version must be semantic")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("pointer manifest digest must be exact SHA-256")
        prefix = self.bundle.get("key_prefix")
        if prefix != f"model-bundles/{version}/":
            raise ValueError("pointer bundle prefix must match the exact model version")
        version_ids = self.bundle.get("object_version_ids")
        if not isinstance(version_ids, dict) or set(version_ids) != MODEL_BUNDLE_FILENAMES:
            raise ValueError("pointer must pin every exact model-bundle S3 VersionId")
        if not all(
            isinstance(item, str)
            and 1 <= len(item) <= 1024
            and not any(ord(character) < 32 for character in item)
            for item in version_ids.values()
        ):
            raise ValueError("pointer S3 VersionIds are invalid")
        return self


class PreflightContext(StrictModel):
    account_id: str = Field(pattern=r"^[0-9]{12}$")
    region: str = Field(pattern=r"^[a-z]{2}(-[a-z]+)+-[0-9]+$")
    project: Literal["modelguard-ai"]
    environment: Literal["demo"]
    deployment_governance_mode: Literal["team_protected", "solo_portfolio"]
    backend_bucket: str = Field(min_length=3)
    backend_key: Literal["modelguard-ai/demo/terraform.tfstate"]
    backend_kms_key_arn: str = Field(
        pattern=r"^arn:aws:kms:[a-z0-9-]+:[0-9]{12}:key/[0-9a-fA-F-]{36}$"
    )
    workspace: Literal["default"]
    alert_kms_key_arn: str = Field(
        pattern=r"^arn:aws:kms:[a-z0-9-]+:[0-9]{12}:key/[0-9a-fA-F-]{36}$"
    )
    stage: Literal["prerequisites", "activation", "destroy"]
    activate_services: bool
    teardown_authorized: bool = False
    runtime_contract_verified: bool = False
    budget_prerequisite_verified: bool = False
    alb_allowed_cidr: str
    access_mode: Literal["https_token", "http_cidr_only"]
    acm_certificate_arn: str | None = None
    prediction_token_ssm_arn: str | None = None
    image_refs: dict[str, str | None]
    active_pointer: ActivePointer | None = None
    model_bucket: str
    auto_destroy_date: date

    @field_validator("alb_allowed_cidr")
    @classmethod
    def cidr_is_restricted(cls, value: str) -> str:
        try:
            return validate_restricted_cidr(value)
        except GuardError as error:
            raise ValueError(str(error)) from error

    @model_validator(mode="after")
    def barriers(self) -> PreflightContext:
        if self.backend_bucket != _expected_backend_bucket(self.account_id, self.region):
            raise ValueError("backend bucket does not match the guarded account and Region")
        if self.model_bucket != _expected_model_bucket(self.account_id, self.region):
            raise ValueError("model bucket does not match the guarded account and Region")
        expected_key_prefix = f"arn:aws:kms:{self.region}:{self.account_id}:key/"
        if not self.backend_kms_key_arn.startswith(expected_key_prefix):
            raise ValueError("backend KMS key does not match the guarded account and Region")
        if self.alert_kms_key_arn != self.backend_kms_key_arn:
            raise ValueError("alert KMS key must be the exact retained bootstrap key")
        expected_activation = self.stage == "activation"
        expected_teardown = self.stage == "destroy"
        if self.activate_services != expected_activation:
            raise ValueError("saved-plan stage and activation flag disagree")
        if self.teardown_authorized != expected_teardown:
            raise ValueError("saved-plan stage and teardown authorization disagree")
        if not self.teardown_authorized and self.auto_destroy_date < datetime.now(tz=UTC).date():
            raise ValueError("AutoDestroyDate has expired")
        if self.auto_destroy_date > datetime.now(tz=UTC).date() + timedelta(days=14):
            raise ValueError("AutoDestroyDate exceeds the 14-day demo window")
        if self.access_mode == "https_token":
            expected_acm_prefix = f"arn:aws:acm:{self.region}:{self.account_id}:certificate/"
            if self.acm_certificate_arn is None or not self.acm_certificate_arn.startswith(
                expected_acm_prefix
            ):
                raise ValueError("https_token requires an ACM certificate ARN")
            if (
                self.prediction_token_ssm_arn is None
                or TOKEN_ARN_PATTERN.fullmatch(self.prediction_token_ssm_arn) is None
                or not self.prediction_token_ssm_arn.startswith(
                    f"arn:aws:ssm:{self.region}:{self.account_id}:"
                    f"parameter/{PROJECT}/{ENVIRONMENT}/secrets/"
                )
            ):
                raise ValueError("https_token requires only the approved SecureString ARN")
        elif self.acm_certificate_arn is not None or self.prediction_token_ssm_arn is not None:
            raise ValueError("http_cidr_only forbids token and certificate inputs")
        if set(self.image_refs) != {"api", "dashboard", "monitor"}:
            raise ValueError("exactly three component image references are required")
        if self.stage == "activation":
            if not self.runtime_contract_verified:
                raise ValueError("activation runtime image contract is not verified")
            if not self.budget_prerequisite_verified:
                raise ValueError("activation USD 10 budget prerequisite is not verified")
            if self.active_pointer is None:
                raise ValueError("activation requires a promoted active pointer")
            if self.active_pointer.bundle.get("bucket") != self.model_bucket:
                raise ValueError("active pointer targets the wrong model bucket")
            image_identities_are_exact = all(
                isinstance(reference, str)
                and IMAGE_PATTERN.fullmatch(reference)
                and reference.startswith(
                    _expected_image_prefix(self.account_id, self.region, component)
                )
                for component, reference in self.image_refs.items()
            )
            if not image_identities_are_exact:
                raise ValueError("activation requires three immutable image digests")
        elif any(reference is not None for reference in self.image_refs.values()):
            raise ValueError("dormant stages must not smuggle activation image references")
        if self.stage != "activation" and self.budget_prerequisite_verified:
            raise ValueError("dormant stage must not claim the activation budget preflight")
        if self.stage == "destroy" and (
            self.runtime_contract_verified or self.active_pointer is not None
        ):
            raise ValueError("destroy runtime inputs must remain dormant")
        return self


def classify_destroy_plan_source_state(payload: Any) -> SourceActivationState:
    """Derive bounded pre-destroy runtime state from saved-plan before-values."""

    if not isinstance(payload, dict):
        raise GuardError("destroy_plan_json_root_not_object")
    resource_changes = payload.get("resource_changes")
    if not isinstance(resource_changes, list):
        raise GuardError("destroy_plan_resource_changes_invalid")
    critical = {
        "module.api_service.aws_ecs_service.this": "desired_count",
        "module.dashboard_service.aws_ecs_service.this": "desired_count",
        "aws_scheduler_schedule.monitor": "state",
    }
    observed: dict[str, Any] = {}
    for raw_change in resource_changes:
        if not isinstance(raw_change, dict):
            raise GuardError("destroy_plan_resource_change_invalid")
        address = raw_change.get("address")
        if address not in critical or "deposed" in raw_change:
            continue
        if address in observed:
            raise GuardError("destroy_plan_source_address_duplicate")
        change = raw_change.get("change")
        before = change.get("before") if isinstance(change, dict) else None
        observed[address] = before.get(critical[address]) if isinstance(before, dict) else None

    api_count = observed.get("module.api_service.aws_ecs_service.this")
    dashboard_count = observed.get("module.dashboard_service.aws_ecs_service.this")
    schedule_state = observed.get("aws_scheduler_schedule.monitor")
    if (
        api_count == 1
        and not isinstance(api_count, bool)
        and dashboard_count == 1
        and not isinstance(dashboard_count, bool)
        and schedule_state == "ENABLED"
    ):
        return "active"
    if (
        api_count == 0
        and not isinstance(api_count, bool)
        and dashboard_count == 0
        and not isinstance(dashboard_count, bool)
        and schedule_state == "DISABLED"
    ):
        return "dormant"
    return "mixed_or_partial"


def verify_empty_managed_state(payload: Any) -> None:
    """Require a structurally valid Terraform state with zero managed resources."""

    if not isinstance(payload, dict):
        raise GuardError("terraform_state_root_not_object")
    if (
        not isinstance(payload.get("version"), int)
        or isinstance(payload.get("version"), bool)
        or not isinstance(payload.get("terraform_version"), str)
        or not isinstance(payload.get("serial"), int)
        or isinstance(payload.get("serial"), bool)
        or not isinstance(payload.get("lineage"), str)
        or not payload["lineage"]
    ):
        raise GuardError("terraform_state_identity_invalid")
    resources = payload.get("resources", [])
    if not isinstance(resources, list):
        raise GuardError("terraform_state_resources_invalid")
    for resource in resources:
        if not isinstance(resource, dict) or resource.get("mode") not in {"data", "managed"}:
            raise GuardError("terraform_state_resource_invalid")
        if resource["mode"] == "managed":
            raise GuardError("terraform_state_managed_resources_remain")


class PlanManifest(StrictModel):
    schema_version: Literal["modelguard.saved-plan-identity.v2"] = SCHEMA_VERSION
    stage: Literal["prerequisites", "activation", "destroy"]
    plan_filename: str
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    variable_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backend_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    account_id: str = Field(pattern=r"^[0-9]{12}$")
    region: str = Field(pattern=r"^[a-z]{2}(-[a-z]+)+-[0-9]+$")
    project: Literal["modelguard-ai"]
    environment: Literal["demo"]
    backend_bucket: str
    backend_key: Literal["modelguard-ai/demo/terraform.tfstate"]
    workspace: Literal["default"]
    git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    owner_tag: str = Field(pattern=r"^[A-Za-z0-9._-]{2,64}$")
    deployment_governance_mode: Literal["team_protected", "solo_portfolio"]
    activate_services: bool
    teardown_authorized: bool
    source_activation_state: SourceActivationState | None
    auto_destroy_date: date
    sealed_at: datetime

    @model_validator(mode="after")
    def stage_identity(self) -> PlanManifest:
        if "@" in self.owner_tag:
            raise ValueError("saved plan owner tag cannot contain an email address")
        if self.plan_filename != PLAN_NAMES[self.stage]:
            raise ValueError("saved plan filename does not match its stage")
        if self.stage != "activation" and self.activate_services:
            raise ValueError("dormant manifest cannot activate services")
        if self.stage == "activation" and not self.activate_services:
            raise ValueError("activation manifest must activate services")
        if self.teardown_authorized != (self.stage == "destroy"):
            raise ValueError("manifest teardown authorization does not match its stage")
        if self.stage == "destroy" and self.source_activation_state is None:
            raise ValueError("destroy manifest must bind the pre-destroy source state")
        if self.stage != "destroy" and self.source_activation_state is not None:
            raise ValueError("non-destroy manifest cannot claim a pre-destroy source state")
        if self.sealed_at.utcoffset() != timedelta(0):
            raise ValueError("sealed_at must be UTC")
        if self.backend_bucket != _expected_backend_bucket(self.account_id, self.region):
            raise ValueError("saved plan backend bucket does not match its account and Region")
        return self


def _backend_values(path: Path) -> dict[str, str]:
    _require_private_regular_file(path, label="backend_config")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", maxsplit=1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([a-z_]+)\s*=\s*(?:\"([^\"]*)\"|(true|false))", line)
        if match is None:
            raise GuardError("backend_config_not_strict_hcl")
        values[match.group(1)] = match.group(2) or match.group(3)
    required = {"bucket", "key", "region", "encrypt", "kms_key_id", "use_lockfile"}
    if set(values) != required:
        raise GuardError("backend_config_fields_mismatch")
    if values["key"] != BACKEND_KEY:
        raise GuardError("backend_key_mismatch")
    if values["encrypt"] != "true" or values["use_lockfile"] != "true":
        raise GuardError("backend_encryption_or_lock_disabled")
    if not values["kms_key_id"].startswith("arn:"):
        raise GuardError("backend_kms_key_missing")
    return values


def _validate_backend_identity(values: dict[str, str], *, account_id: str, region: str) -> None:
    if (
        re.fullmatch(r"[0-9]{12}", account_id) is None
        or re.fullmatch(r"[a-z]{2}(-[a-z]+)+-[0-9]+", region) is None
    ):
        raise GuardError("backend_account_or_region_invalid")
    if values["region"] != region:
        raise GuardError("backend_region_mismatch")
    if values["bucket"] != _expected_backend_bucket(account_id, region):
        raise GuardError("backend_bucket_mismatch")
    expected_key_pattern = re.compile(
        rf"^arn:aws:kms:{re.escape(region)}:{re.escape(account_id)}:key/[A-Za-z0-9-]+$"
    )
    if expected_key_pattern.fullmatch(values["kms_key_id"]) is None:
        raise GuardError("backend_kms_key_identity_mismatch")


def verify_active_pointer_binding(
    *,
    pointer_response: dict[str, Any],
    variable_file: Path,
    account_id: str,
    region: str,
) -> None:
    """Require the live non-secret pointer to equal the activation inputs exactly."""

    parameter = pointer_response.get("Parameter")
    if not isinstance(parameter, dict):
        raise GuardError("active_pointer_parameter_missing")
    if (
        parameter.get("Name") != f"/{PROJECT}/{ENVIRONMENT}/models/active"
        or parameter.get("Type") != "String"
        or not isinstance(parameter.get("Value"), str)
    ):
        raise GuardError("active_pointer_parameter_identity_invalid")
    try:
        pointer_payload = parse_strict_json_bytes(parameter["Value"].encode("utf-8"))
    except ValueError as error:
        raise GuardError("active_pointer_value_json_invalid") from error
    if not isinstance(pointer_payload, dict):
        raise GuardError("active_pointer_value_not_object")
    pointer = ActivePointer.model_validate(pointer_payload)
    tfvars = _load_json(variable_file)
    expected = {
        "stage": tfvars.get("deployment_stage"),
        "activate_services": tfvars.get("activate_services"),
        "model_version": tfvars.get("expected_model_version"),
        "manifest_sha256": tfvars.get("expected_model_manifest_sha256"),
        "object_version_ids": tfvars.get("expected_model_object_version_ids"),
        "bucket": f"{PROJECT}-{ENVIRONMENT}-{account_id}-{region}-models",
    }
    actual = {
        "stage": "activation",
        "activate_services": True,
        "model_version": pointer.target_identity["model_version"],
        "manifest_sha256": pointer.target_identity["bundle_manifest_sha256"],
        "object_version_ids": pointer.bundle["object_version_ids"],
        "bucket": pointer.bundle["bucket"],
    }
    if expected != actual:
        raise GuardError("active_pointer_activation_binding_mismatch")


def seal_plan(
    *,
    plan_path: Path,
    variable_file: Path,
    backend_config: Path,
    stage: Literal["prerequisites", "activation", "destroy"],
    account_id: str,
    region: str,
    auto_destroy_date: date,
    activate_services: bool,
    source_activation_state: SourceActivationState | None = None,
    repository: Path,
    now: datetime | None = None,
) -> PlanManifest:
    """Bind one opaque saved plan to every identity reviewed by the operator."""

    _verify_clean_repository(repository)
    if plan_path.name != PLAN_NAMES[stage]:
        raise GuardError("saved_plan_filename_mismatch")
    _require_private_regular_file(plan_path, label="saved_plan")
    _require_private_regular_file(variable_file, label="rendered_tfvars")
    _require_private_regular_file(backend_config, label="backend_config")
    tfvars = _load_rendered_tfvars(variable_file)
    _validate_rendered_tfvars(
        tfvars,
        stage=stage,
        account_id=account_id,
        region=region,
        auto_destroy_date=auto_destroy_date,
    )
    backend = _backend_values(backend_config)
    _validate_backend_identity(backend, account_id=account_id, region=region)
    return PlanManifest(
        stage=stage,
        plan_filename=plan_path.name,
        plan_sha256=_sha256(plan_path),
        variable_file_sha256=_sha256(variable_file),
        backend_config_sha256=_sha256(backend_config),
        account_id=account_id,
        region=region,
        project=PROJECT,
        environment=ENVIRONMENT,
        backend_bucket=backend["bucket"],
        backend_key=BACKEND_KEY,
        workspace="default",
        git_commit=_git_commit(repository),
        owner_tag=tfvars["owner_tag"],
        deployment_governance_mode=tfvars["deployment_governance_mode"],
        activate_services=activate_services,
        teardown_authorized=tfvars["teardown_authorized"],
        source_activation_state=source_activation_state,
        auto_destroy_date=auto_destroy_date,
        sealed_at=now or datetime.now(tz=UTC),
    )


def verify_plan(
    manifest: PlanManifest,
    *,
    plan_path: Path,
    variable_file: Path,
    backend_config: Path,
    account_id: str,
    region: str,
    stage: Literal["prerequisites", "activation", "destroy"],
    repository: Path,
    today: date | None = None,
    now: datetime | None = None,
) -> None:
    """Refuse a stale, renamed, modified, or cross-identity saved plan."""

    _verify_clean_repository(repository)
    _require_private_regular_file(plan_path, label="saved_plan")
    _require_private_regular_file(variable_file, label="rendered_tfvars")
    _require_private_regular_file(backend_config, label="backend_config")
    tfvars = _load_rendered_tfvars(variable_file)
    _validate_rendered_tfvars(
        tfvars,
        stage=stage,
        account_id=account_id,
        region=region,
        auto_destroy_date=manifest.auto_destroy_date,
    )
    backend = _backend_values(backend_config)
    _validate_backend_identity(backend, account_id=account_id, region=region)
    expected = {
        "stage": (manifest.stage, stage),
        "plan_filename": (manifest.plan_filename, plan_path.name),
        "plan_sha256": (manifest.plan_sha256, _sha256(plan_path)),
        "variable_file_sha256": (manifest.variable_file_sha256, _sha256(variable_file)),
        "backend_config_sha256": (manifest.backend_config_sha256, _sha256(backend_config)),
        "account_id": (manifest.account_id, account_id),
        "region": (manifest.region, region),
        "backend_bucket": (manifest.backend_bucket, backend["bucket"]),
        "backend_key": (manifest.backend_key, backend["key"]),
        "git_commit": (manifest.git_commit, _git_commit(repository)),
        "owner_tag": (manifest.owner_tag, tfvars["owner_tag"]),
        "deployment_governance_mode": (
            manifest.deployment_governance_mode,
            tfvars["deployment_governance_mode"],
        ),
        "activate_services": (manifest.activate_services, tfvars["activate_services"]),
        "teardown_authorized": (
            manifest.teardown_authorized,
            tfvars["teardown_authorized"],
        ),
    }
    mismatches = [name for name, (actual, wanted) in expected.items() if actual != wanted]
    if mismatches:
        raise GuardError(f"saved_plan_identity_mismatch:{','.join(sorted(mismatches))}")
    if manifest.project != PROJECT or manifest.environment != ENVIRONMENT:
        raise GuardError("saved_plan_project_environment_mismatch")
    if manifest.workspace != "default":
        raise GuardError("terraform_workspace_mismatch")
    evaluation_time = now or datetime.now(tz=UTC)
    if evaluation_time.utcoffset() != timedelta(0):
        raise GuardError("saved_plan_evaluation_time_not_utc")
    plan_age = evaluation_time - manifest.sealed_at
    if plan_age < -MAX_SAVED_PLAN_CLOCK_SKEW:
        raise GuardError("saved_plan_sealed_at_in_future")
    if plan_age > MAX_SAVED_PLAN_AGE:
        raise GuardError("saved_plan_expired")
    if stage != "destroy" and manifest.auto_destroy_date < (today or datetime.now(tz=UTC).date()):
        raise GuardError("saved_plan_auto_destroy_date_expired")


def evaluate_post_destroy_inventory(
    payload: dict[str, Any],
    *,
    account_id: str,
    region: str,
    project: str = PROJECT,
    environment: str = ENVIRONMENT,
) -> dict[str, list[str]]:
    """Classify AWS tag-inventory evidence and fail closed on malformed records."""

    if (
        re.fullmatch(r"[0-9]{12}", account_id) is None
        or re.fullmatch(r"[a-z]{2}(-[a-z]+)+-[0-9]+", region) is None
        or project != PROJECT
        or environment != ENVIRONMENT
    ):
        raise GuardError("inventory_expected_identity_invalid")
    if payload.get("schema_version") != POST_DESTROY_INVENTORY_SCHEMA_VERSION:
        raise GuardError("inventory_schema_version_invalid")
    if set(payload) != {
        "schema_version",
        "identity",
        "ResourceTagMappingList",
        "service_residuals",
        "retained_resources",
        "nonbillable_metadata",
    }:
        raise GuardError("inventory_schema_fields_mismatch")

    identity = payload["identity"]
    if not isinstance(identity, dict) or set(identity) != {
        "account_id",
        "region",
        "project",
        "environment",
    }:
        raise GuardError("inventory_identity_invalid")
    payload_account_id = identity.get("account_id")
    payload_region = identity.get("region")
    if (
        not isinstance(payload_account_id, str)
        or re.fullmatch(r"[0-9]{12}", payload_account_id) is None
        or not isinstance(payload_region, str)
        or re.fullmatch(r"[a-z]{2}(-[a-z]+)+-[0-9]+", payload_region) is None
        or identity.get("project") != project
        or identity.get("environment") != environment
    ):
        raise GuardError("inventory_identity_invalid")
    if payload_account_id != account_id or payload_region != region:
        raise GuardError("inventory_identity_mismatch")

    raw_resources = payload["ResourceTagMappingList"]
    if not isinstance(raw_resources, list):
        raise GuardError("inventory_resource_list_missing")
    result: dict[str, list[str]] = {
        "residual_demo": [],
        "residual_service": [],
        "retained_bootstrap": [],
        "retained_budget": [],
        "validated_nonbillable": [],
        "unrelated": [],
    }
    for item in raw_resources:
        if not isinstance(item, dict) or set(item) != {"ResourceARN", "Tags"}:
            raise GuardError("inventory_resource_invalid")
        arn = item["ResourceARN"]
        raw_tags = item["Tags"]
        if not isinstance(arn, str) or not arn.startswith("arn:"):
            raise GuardError("inventory_arn_invalid")
        if not isinstance(raw_tags, list):
            raise GuardError("inventory_tags_invalid")
        tags: dict[str, str] = {}
        for tag in raw_tags:
            if (
                not isinstance(tag, dict)
                or set(tag) != {"Key", "Value"}
                or not isinstance(tag.get("Key"), str)
                or not isinstance(tag.get("Value"), str)
                or tag["Key"] in tags
            ):
                raise GuardError("inventory_tags_invalid")
            tags[tag["Key"]] = tag["Value"]
        if tags.get("Project") == project and tags.get("Environment") == environment:
            result["residual_demo"].append(arn)
        else:
            raise GuardError("inventory_resource_tag_scope_mismatch")

    service_residuals = payload["service_residuals"]
    if (
        not isinstance(service_residuals, dict)
        or set(service_residuals) != POST_DESTROY_SERVICE_CATEGORIES
    ):
        raise GuardError("inventory_service_residuals_invalid")
    for service, identifiers in service_residuals.items():
        if not isinstance(identifiers, list):
            raise GuardError("inventory_service_residuals_invalid")
        seen: set[str] = set()
        for identifier in identifiers:
            if not isinstance(identifier, str) or not identifier.strip():
                raise GuardError("inventory_service_identifier_invalid")
            if identifier in seen:
                raise GuardError("inventory_service_identifier_duplicate")
            seen.add(identifier)
            result["residual_service"].append(f"{service}:{identifier}")

    retained_resources = payload["retained_resources"]
    if not isinstance(retained_resources, dict) or set(retained_resources) != {"budgets"}:
        raise GuardError("inventory_retained_resources_invalid")
    budgets = retained_resources["budgets"]
    if budgets != [POST_DESTROY_RETAINED_BUDGET]:
        raise GuardError("inventory_retained_budget_invalid")
    result["retained_budget"].extend(budgets)

    nonbillable_metadata = payload["nonbillable_metadata"]
    if not isinstance(nonbillable_metadata, dict) or set(nonbillable_metadata) != {
        "ecs_task_definitions_inactive"
    }:
        raise GuardError("inventory_nonbillable_metadata_invalid")
    inactive_task_definitions = nonbillable_metadata["ecs_task_definitions_inactive"]
    if not isinstance(inactive_task_definitions, list):
        raise GuardError("inventory_nonbillable_metadata_invalid")
    task_family_pattern = "|".join(POST_DESTROY_TASK_FAMILIES)
    inactive_pattern = re.compile(
        rf"^arn:aws:ecs:{re.escape(region)}:{re.escape(account_id)}:task-definition/"
        rf"modelguard-ai-demo-(?:{task_family_pattern}):[1-9][0-9]*$"
    )
    seen_inactive: set[str] = set()
    for identifier in inactive_task_definitions:
        if not isinstance(identifier, str) or inactive_pattern.fullmatch(identifier) is None:
            raise GuardError("inventory_inactive_task_definition_invalid")
        if identifier in seen_inactive:
            raise GuardError("inventory_inactive_task_definition_duplicate")
        seen_inactive.add(identifier)
        result["validated_nonbillable"].append(f"ecs_task_definitions_inactive:{identifier}")
    return {key: sorted(values) for key, values in result.items()}


def _inventory_summary(
    *,
    account_id: str,
    region: str,
    status: Literal["passed", "refused"],
    result: dict[str, list[str]] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Return only masked identity and counts suitable for public logs."""

    masked_account = (
        f"********{account_id[-4:]}" if re.fullmatch(r"[0-9]{12}", account_id) else "invalid"
    )
    safe_region = (
        region if re.fullmatch(r"[a-z]{2}(-[a-z]+)+-[0-9]+", region) is not None else "invalid"
    )
    summary: dict[str, Any] = {
        "account_id_masked": masked_account,
        "category_counts": {
            category: len(result[category]) if result is not None else 0
            for category in POST_DESTROY_RESULT_CATEGORIES
        },
        "guard": "verify-inventory",
        "region": safe_region,
        "status": status,
    }
    if reason is not None:
        summary["reason"] = reason
    return summary


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = parse_strict_json_bytes(path.read_bytes())
    except (OSError, ValueError) as error:
        raise GuardError("json_invalid") from error
    if not isinstance(value, dict):
        raise GuardError("json_root_not_object")
    return value


def _strict_inventory_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise GuardError("inventory_evidence_duplicate_key")
        value[key] = item
    return value


def _reject_inventory_json_constant(_: str) -> None:
    raise GuardError("inventory_evidence_non_finite_number")


def load_post_destroy_inventory(path: Path) -> dict[str, Any]:
    """Load owner-only inventory evidence from one regular path and directory."""

    directory_descriptor: int | None = None
    file_descriptor: int | None = None
    try:
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        directory_descriptor = os.open(path.parent, directory_flags)
        parent_metadata = os.fstat(directory_descriptor)
        file_descriptor = os.open(
            path.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_descriptor,
        )
        metadata = os.fstat(file_descriptor)
    except OSError as error:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        raise GuardError("inventory_evidence_unavailable") from error
    if directory_descriptor is None or file_descriptor is None:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        raise GuardError("inventory_evidence_unavailable")
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(parent_metadata.st_mode) != 0o700
    ):
        os.close(file_descriptor)
        os.close(directory_descriptor)
        raise GuardError("inventory_evidence_parent_invalid")
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        os.close(file_descriptor)
        os.close(directory_descriptor)
        raise GuardError("inventory_evidence_file_invalid")
    try:
        with os.fdopen(file_descriptor, encoding="utf-8") as handle:
            file_descriptor = None
            value = json.load(
                handle,
                object_pairs_hook=_strict_inventory_json_pairs,
                parse_constant=_reject_inventory_json_constant,
            )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GuardError("inventory_evidence_json_invalid") from error
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        os.close(directory_descriptor)
    if not isinstance(value, dict):
        raise GuardError("inventory_evidence_root_not_object")
    return value


def load_plan_manifest(path: Path) -> PlanManifest:
    """Load only a regular owner-only plan manifest, never a symlink."""

    try:
        metadata = path.lstat()
    except OSError as error:
        raise GuardError("saved_plan_manifest_unavailable") from error
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise GuardError("saved_plan_manifest_not_regular")
    if metadata.st_uid != os.geteuid():
        raise GuardError("saved_plan_manifest_owner_invalid")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise GuardError("saved_plan_manifest_mode_invalid")
    try:
        return PlanManifest.model_validate(_load_json(path))
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise GuardError("saved_plan_manifest_invalid") from error


def write_plan_manifest(path: Path, manifest: PlanManifest) -> None:
    """Publish one immutable manifest atomically with owner-only permissions."""

    payload = (
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        parent_metadata = path.parent.lstat()
    except OSError as error:
        raise GuardError("saved_plan_manifest_parent_unavailable") from error
    if not stat.S_ISDIR(parent_metadata.st_mode) or stat.S_ISLNK(parent_metadata.st_mode):
        raise GuardError("saved_plan_manifest_parent_not_directory")
    temporary_path: Path | None = None
    try:
        file_descriptor, raw_temporary_path = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(raw_temporary_path)
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600, follow_symlinks=False)
        os.link(temporary_path, path, follow_symlinks=False)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_descriptor = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except FileExistsError as error:
        raise GuardError("saved_plan_manifest_output_exists") from error
    except OSError as error:
        raise GuardError("saved_plan_manifest_write_failed") from error
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
    try:
        metadata = path.lstat()
    except OSError as error:
        raise GuardError("saved_plan_manifest_write_failed") from error
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise GuardError("saved_plan_manifest_not_regular")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise GuardError("saved_plan_manifest_mode_invalid")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="terraform-demo-guard")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight", help="validate a non-secret plan context JSON")
    preflight.add_argument("--input", type=Path, required=True)
    preflight.add_argument("--account-id", required=True)
    preflight.add_argument("--region", required=True)
    preflight.add_argument(
        "--stage", choices=("prerequisites", "activation", "destroy"), required=True
    )
    preflight.add_argument("--backend-bucket", required=True)

    inventory = subparsers.add_parser(
        "verify-inventory", help="verify tagged post-destroy inventory"
    )
    inventory.add_argument("--input", type=Path, required=True)
    inventory.add_argument("--account-id", required=True)
    inventory.add_argument("--region", required=True)

    backend = subparsers.add_parser("verify-backend", help="verify backend identity before init")
    backend.add_argument("--input", type=Path, required=True)
    backend.add_argument("--bucket", required=True)
    backend.add_argument("--account-id", required=True)
    backend.add_argument("--region", required=True)

    pointer = subparsers.add_parser(
        "verify-active-pointer", help="verify the live pointer against activation tfvars"
    )
    pointer.add_argument("--pointer-response", type=Path, required=True)
    pointer.add_argument("--var-file", type=Path, required=True)
    pointer.add_argument("--account-id", required=True)
    pointer.add_argument("--region", required=True)

    subparsers.add_parser(
        "classify-destroy-plan-source-state",
        help="classify private destroy-plan before-values without emitting them",
    )
    subparsers.add_parser(
        "verify-empty-managed-state",
        help="verify a private Terraform state JSON stream has no managed resources",
    )

    for command in ("seal-plan", "verify-plan"):
        item = subparsers.add_parser(command)
        item.add_argument("--plan", type=Path, required=True)
        item.add_argument("--var-file", type=Path, required=True)
        item.add_argument("--backend-config", type=Path, required=True)
        item.add_argument("--stage", choices=tuple(PLAN_NAMES), required=True)
        item.add_argument("--account-id", required=True)
        item.add_argument("--region", required=True)
        item.add_argument("--repository", type=Path, default=Path.cwd())
    seal = subparsers.choices["seal-plan"]
    seal.add_argument("--auto-destroy-date", type=date.fromisoformat, required=True)
    seal.add_argument("--activate-services", choices=("true", "false"), required=True)
    seal.add_argument(
        "--source-activation-state",
        choices=("active", "dormant", "mixed_or_partial"),
    )
    seal.add_argument("--output", type=Path, required=True)
    verify = subparsers.choices["verify-plan"]
    verify.add_argument("--manifest", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "preflight":
            context = PreflightContext.model_validate(_load_json(args.input))
            expected = {
                "account_id": (context.account_id, args.account_id),
                "region": (context.region, args.region),
                "stage": (context.stage, args.stage),
                "backend_bucket": (context.backend_bucket, args.backend_bucket),
            }
            mismatches = [name for name, (actual, wanted) in expected.items() if actual != wanted]
            if mismatches:
                raise GuardError(f"preflight_identity_mismatch:{','.join(sorted(mismatches))}")
            print('{"status":"passed","guard":"preflight"}')
            return 0
        if args.command == "verify-inventory":
            try:
                result = evaluate_post_destroy_inventory(
                    load_post_destroy_inventory(args.input),
                    account_id=args.account_id,
                    region=args.region,
                )
            except (GuardError, OSError, ValueError) as error:
                reason = _safe_failure_reason(error, maximum=120)
                print(
                    json.dumps(
                        _inventory_summary(
                            account_id=args.account_id,
                            region=args.region,
                            status="refused",
                            reason=reason,
                        ),
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                )
                return 2
            residuals_remain = bool(
                result["residual_demo"] or result["residual_service"] or result["unrelated"]
            )
            status: Literal["passed", "refused"] = "refused" if residuals_remain else "passed"
            summary = _inventory_summary(
                account_id=args.account_id,
                region=args.region,
                status=status,
                result=result,
                reason="post_destroy_demo_resources_remain" if residuals_remain else None,
            )
            print(
                json.dumps(summary, separators=(",", ":"), sort_keys=True),
                file=sys.stderr if residuals_remain else sys.stdout,
            )
            return 2 if residuals_remain else 0
        if args.command == "verify-backend":
            backend = _backend_values(args.input)
            if backend["bucket"] != args.bucket or backend["region"] != args.region:
                raise GuardError("backend_bucket_or_region_mismatch")
            _validate_backend_identity(
                backend,
                account_id=args.account_id,
                region=args.region,
            )
            print('{"status":"passed","guard":"verify-backend"}')
            return 0
        if args.command == "verify-active-pointer":
            verify_active_pointer_binding(
                pointer_response=_load_json(args.pointer_response),
                variable_file=args.var_file,
                account_id=args.account_id,
                region=args.region,
            )
            print('{"status":"passed","guard":"verify-active-pointer"}')
            return 0
        if args.command == "classify-destroy-plan-source-state":
            raw_plan = sys.stdin.buffer.read(MAX_TERRAFORM_STATE_BYTES + 1)
            if not raw_plan or len(raw_plan) > MAX_TERRAFORM_STATE_BYTES:
                raise GuardError("destroy_plan_json_size_invalid")
            try:
                plan = parse_strict_json_bytes(raw_plan)
            except ValueError as error:
                raise GuardError("destroy_plan_json_invalid") from error
            print(classify_destroy_plan_source_state(plan))
            return 0
        if args.command == "verify-empty-managed-state":
            raw_state = sys.stdin.buffer.read(MAX_TERRAFORM_STATE_BYTES + 1)
            if not raw_state or len(raw_state) > MAX_TERRAFORM_STATE_BYTES:
                raise GuardError("terraform_state_size_invalid")
            try:
                state = parse_strict_json_bytes(raw_state)
            except ValueError as error:
                raise GuardError("terraform_state_json_invalid") from error
            verify_empty_managed_state(state)
            print('{"status":"passed","managed_resources":0}')
            return 0
        if args.command == "seal-plan":
            manifest = seal_plan(
                plan_path=args.plan,
                variable_file=args.var_file,
                backend_config=args.backend_config,
                stage=args.stage,
                account_id=args.account_id,
                region=args.region,
                auto_destroy_date=args.auto_destroy_date,
                activate_services=args.activate_services == "true",
                source_activation_state=args.source_activation_state,
                repository=args.repository,
            )
            write_plan_manifest(args.output, manifest)
            print('{"status":"passed","guard":"seal-plan"}')
            return 0
        manifest = load_plan_manifest(args.manifest)
        verify_plan(
            manifest,
            plan_path=args.plan,
            variable_file=args.var_file,
            backend_config=args.backend_config,
            account_id=args.account_id,
            region=args.region,
            stage=args.stage,
            repository=args.repository,
        )
        print('{"status":"passed","guard":"verify-plan"}')
        return 0
    except (GuardError, OSError, subprocess.SubprocessError, ValidationError, ValueError) as error:
        category = _safe_failure_reason(error)
        print(json.dumps({"status": "refused", "reason": category}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
