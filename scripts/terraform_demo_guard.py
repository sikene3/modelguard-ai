#!/usr/bin/env python3
"""Pure Phase 08 deployment guards; no AWS or Terraform mutation is performed here."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re

# Subprocess is limited to the fixed local Git identity command in _git_commit.
import subprocess  # nosec B404
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SCHEMA_VERSION: Literal["modelguard.saved-plan-identity.v1"] = "modelguard.saved-plan-identity.v1"
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit(repository: Path) -> str:
    # Fixed local executable and arguments; no user-controlled shell interpretation occurs.
    result = subprocess.run(  # nosec B603, B607
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise GuardError("git_commit_invalid")
    return commit


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
    runtime_contract_verified: bool = False
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
        if self.stage != "destroy" and self.activate_services != expected_activation:
            raise ValueError("saved-plan stage and activation flag disagree")
        if self.stage == "destroy" and not self.activate_services:
            # Destroy may start from either active or prerequisite state; the saved plan identity,
            # not this flag, is authoritative for destructive intent.
            pass
        if self.auto_destroy_date < datetime.now(tz=UTC).date():
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
        elif self.stage == "prerequisites" and any(
            reference is not None for reference in self.image_refs.values()
        ):
            raise ValueError("prerequisites must not smuggle activation image references")
        return self


class PlanManifest(StrictModel):
    schema_version: Literal["modelguard.saved-plan-identity.v1"] = SCHEMA_VERSION
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
    activate_services: bool
    auto_destroy_date: date
    sealed_at: datetime

    @model_validator(mode="after")
    def stage_identity(self) -> PlanManifest:
        if self.plan_filename != PLAN_NAMES[self.stage]:
            raise ValueError("saved plan filename does not match its stage")
        if self.stage == "prerequisites" and self.activate_services:
            raise ValueError("prerequisite manifest cannot activate services")
        if self.stage == "activation" and not self.activate_services:
            raise ValueError("activation manifest must activate services")
        if self.sealed_at.utcoffset() != timedelta(0):
            raise ValueError("sealed_at must be UTC")
        if self.backend_bucket != _expected_backend_bucket(self.account_id, self.region):
            raise ValueError("saved plan backend bucket does not match its account and Region")
        return self


def _backend_values(path: Path) -> dict[str, str]:
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
    pointer_payload = json.loads(parameter["Value"])
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
    repository: Path,
    now: datetime | None = None,
) -> PlanManifest:
    """Bind one opaque saved plan to every identity reviewed by the operator."""

    if plan_path.name != PLAN_NAMES[stage]:
        raise GuardError("saved_plan_filename_mismatch")
    if not all(path.is_file() for path in (plan_path, variable_file, backend_config)):
        raise GuardError("saved_plan_input_missing")
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
        activate_services=activate_services,
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

    if not all(path.is_file() for path in (plan_path, variable_file, backend_config)):
        raise GuardError("saved_plan_input_missing")
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
    project: str = PROJECT,
    environment: str = ENVIRONMENT,
) -> dict[str, list[str]]:
    """Classify AWS tag-inventory evidence and fail closed on malformed records."""

    raw_resources = payload.get("ResourceTagMappingList", payload.get("resources"))
    if not isinstance(raw_resources, list):
        raise GuardError("inventory_resource_list_missing")
    result: dict[str, list[str]] = {
        "residual_demo": [],
        "residual_service": [],
        "retained_bootstrap": [],
        "unrelated": [],
    }
    for item in raw_resources:
        if not isinstance(item, dict):
            raise GuardError("inventory_resource_invalid")
        arn = item.get("ResourceARN", item.get("arn"))
        raw_tags = item.get("Tags", item.get("tags", {}))
        if not isinstance(arn, str) or not arn.startswith("arn:"):
            raise GuardError("inventory_arn_invalid")
        if isinstance(raw_tags, list):
            tags = {
                tag["Key"]: tag["Value"]
                for tag in raw_tags
                if isinstance(tag, dict)
                and isinstance(tag.get("Key"), str)
                and isinstance(tag.get("Value"), str)
            }
        elif isinstance(raw_tags, dict) and all(
            isinstance(key, str) and isinstance(value, str) for key, value in raw_tags.items()
        ):
            tags = raw_tags
        else:
            raise GuardError("inventory_tags_invalid")
        if tags.get("Project") == project and tags.get("Environment") == environment:
            result["residual_demo"].append(arn)
        elif tags.get("Project") == project and tags.get("Ownership") == "bootstrap":
            result["retained_bootstrap"].append(arn)
        else:
            result["unrelated"].append(arn)

    service_residuals = payload.get("service_residuals", {})
    if not isinstance(service_residuals, dict):
        raise GuardError("inventory_service_residuals_invalid")
    for service, identifiers in service_residuals.items():
        if not isinstance(service, str) or not service or not isinstance(identifiers, list):
            raise GuardError("inventory_service_residuals_invalid")
        for identifier in identifiers:
            if not isinstance(identifier, str) or not identifier.strip():
                raise GuardError("inventory_service_identifier_invalid")
            result["residual_service"].append(f"{service}:{identifier}")
    return {key: sorted(values) for key, values in result.items()}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GuardError("json_root_not_object")
    return value


def _write_manifest(path: Path, manifest: PlanManifest) -> None:
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="terraform-demo-guard")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight", help="validate a non-secret plan context JSON")
    preflight.add_argument("--input", type=Path, required=True)
    preflight.add_argument("--account-id", required=True)
    preflight.add_argument("--region", required=True)
    preflight.add_argument("--stage", choices=("prerequisites", "activation"), required=True)
    preflight.add_argument("--backend-bucket", required=True)

    inventory = subparsers.add_parser(
        "verify-inventory", help="verify tagged post-destroy inventory"
    )
    inventory.add_argument("--input", type=Path, required=True)

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
            result = evaluate_post_destroy_inventory(_load_json(args.input))
            print(json.dumps(result, separators=(",", ":"), sort_keys=True))
            if result["residual_demo"] or result["residual_service"]:
                raise GuardError("post_destroy_demo_resources_remain")
            return 0
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
                repository=args.repository,
            )
            _write_manifest(args.output, manifest)
            print('{"status":"passed","guard":"seal-plan"}')
            return 0
        manifest = PlanManifest.model_validate(_load_json(args.manifest))
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
        category = str(error).splitlines()[0][:200]
        print(json.dumps({"status": "refused", "reason": category}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
