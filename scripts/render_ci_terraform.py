#!/usr/bin/env python3
"""Create strict ephemeral backend, tfvars, and Phase 08 preflight inputs for CI."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError

from modelguard.core.serialization import parse_strict_json_bytes
from scripts.terraform_demo_guard import BACKEND_KEY, PreflightContext


class RenderInputError(RuntimeError):
    """A configuration refusal safe to print without input values."""


def _load_pointer(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RenderInputError("active_pointer_root_not_object")
    return value


def _load_runtime_verification(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    value = parse_strict_json_bytes(path.read_bytes())
    if not isinstance(value, dict):
        raise RenderInputError("runtime_verification_root_not_object")
    return value


def _verify_runtime_evidence(
    evidence: dict[str, Any] | None,
    *,
    image_refs: dict[str, str | None],
    expected_source_commit: str | None,
) -> bool:
    if evidence is None:
        return False
    if (
        evidence.get("schema_version") != "modelguard.runtime-contract-verification.v2"
        or evidence.get("status") != "passed"
        or evidence.get("mode") != "immutable_digest"
        or evidence.get("images") != image_refs
        or evidence.get("contracts")
        != {
            "api": "hydration-fail-closed",
            "dashboard": "typed-aws-health",
            "monitor": "one-shot-aws-run",
        }
    ):
        raise RenderInputError("runtime_verification_evidence_mismatch")
    source_commit = evidence.get("source_commit")
    expected_lock_sha256 = _sha256(Path("uv.lock"))
    if (
        expected_source_commit is None
        or re.fullmatch(r"[0-9a-f]{40}", expected_source_commit) is None
        or source_commit != expected_source_commit
        or evidence.get("source_revision") != expected_source_commit
        or evidence.get("uv_lock_sha256") != expected_lock_sha256
    ):
        raise RenderInputError("runtime_verification_source_commit_invalid")
    return True


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_inputs(
    *,
    output_dir: Path,
    stage: Literal["prerequisites", "activation"],
    account_id: str,
    region: str,
    owner_tag: str,
    governance_mode: Literal["team_protected", "solo_portfolio"],
    auto_destroy_date: str,
    backend_bucket: str,
    backend_kms_key_arn: str,
    permission_boundary_arn: str,
    alert_kms_key_arn: str,
    alb_allowed_cidr: str,
    access_mode: Literal["https_token", "http_cidr_only"],
    acm_certificate_arn: str | None = None,
    prediction_token_ssm_arn: str | None = None,
    image_refs: dict[str, str | None] | None = None,
    active_pointer: dict[str, Any] | None = None,
    budget_prerequisite_verified: bool = False,
    runtime_verification: dict[str, Any] | None = None,
    source_commit: str | None = None,
) -> dict[str, Path]:
    """Render ephemeral files and validate the complete non-secret deployment identity."""

    if re.fullmatch(r"[A-Za-z0-9._-]{2,64}", owner_tag) is None or "@" in owner_tag:
        raise RenderInputError("owner_tag_invalid")
    refs = image_refs or {"api": None, "dashboard": None, "monitor": None}
    activate = stage == "activation"
    runtime_verified = _verify_runtime_evidence(
        runtime_verification,
        image_refs=refs,
        expected_source_commit=source_commit,
    )
    if activate and not runtime_verified:
        raise RenderInputError("activation_runtime_verification_missing")
    if not activate and runtime_verification is not None:
        raise RenderInputError("prerequisite_runtime_verification_forbidden")
    model_bucket = f"modelguard-ai-demo-{account_id}-{region}-models"
    preflight_payload = {
        "account_id": account_id,
        "region": region,
        "project": "modelguard-ai",
        "environment": "demo",
        "deployment_governance_mode": governance_mode,
        "backend_bucket": backend_bucket,
        "backend_key": BACKEND_KEY,
        "backend_kms_key_arn": backend_kms_key_arn,
        "workspace": "default",
        "alert_kms_key_arn": alert_kms_key_arn,
        "stage": stage,
        "activate_services": activate,
        "runtime_contract_verified": runtime_verified,
        "budget_prerequisite_verified": budget_prerequisite_verified,
        "alb_allowed_cidr": alb_allowed_cidr,
        "access_mode": access_mode,
        "acm_certificate_arn": acm_certificate_arn,
        "prediction_token_ssm_arn": prediction_token_ssm_arn,
        "image_refs": refs,
        "active_pointer": active_pointer,
        "model_bucket": model_bucket,
        "auto_destroy_date": auto_destroy_date,
    }
    PreflightContext.model_validate(preflight_payload)

    tfvars: dict[str, Any] = {
        "aws_account_id": account_id,
        "aws_region": region,
        "owner_tag": owner_tag,
        "deployment_governance_mode": governance_mode,
        "auto_destroy_date": auto_destroy_date,
        "backend_bucket_name": backend_bucket,
        "permission_boundary_arn": permission_boundary_arn,
        "alert_kms_key_arn": alert_kms_key_arn,
        "alb_allowed_cidr": alb_allowed_cidr,
        "api_access_mode": access_mode,
        "deployment_stage": stage,
        "activate_services": activate,
        "runtime_contract_verified": runtime_verified,
        "budget_prerequisite_verified": budget_prerequisite_verified,
        "availability_zones": [f"{region}a", f"{region}b"],
    }
    if access_mode == "https_token":
        tfvars["acm_certificate_arn"] = acm_certificate_arn
        tfvars["prediction_token_ssm_arn"] = prediction_token_ssm_arn
    if activate:
        if active_pointer is None:
            raise RenderInputError("activation_active_pointer_missing")
        tfvars.update(
            {
                **{f"{component}_image_ref": refs[component] for component in refs},
                "expected_model_version": active_pointer["target_identity"]["model_version"],
                "expected_model_manifest_sha256": active_pointer["target_identity"][
                    "bundle_manifest_sha256"
                ],
                "expected_model_object_version_ids": active_pointer["bundle"]["object_version_ids"],
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    backend_path = output_dir / "backend.hcl"
    tfvars_path = output_dir / "demo-ci.tfvars.json"
    preflight_path = output_dir / "preflight.json"
    backend_path.write_text(
        f'bucket = "{backend_bucket}"\n'
        f'key = "{BACKEND_KEY}"\n'
        f'region = "{region}"\n'
        "encrypt = true\n"
        f'kms_key_id = "{backend_kms_key_arn}"\n'
        "use_lockfile = true\n",
        encoding="utf-8",
    )
    tfvars_path.write_text(json.dumps(tfvars, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    preflight_path.write_text(
        json.dumps(preflight_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for path in (backend_path, tfvars_path, preflight_path):
        path.chmod(0o600)
    return {"backend": backend_path, "tfvars": tfvars_path, "preflight": preflight_path}


def _optional(value: str) -> str | None:
    return value or None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="render-ci-terraform")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stage", choices=("prerequisites", "activation"), required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--owner-tag", required=True)
    parser.add_argument(
        "--governance-mode",
        choices=("team_protected", "solo_portfolio"),
        required=True,
    )
    parser.add_argument("--auto-destroy-date", required=True)
    parser.add_argument("--backend-bucket", required=True)
    parser.add_argument("--backend-kms-key-arn", required=True)
    parser.add_argument("--permission-boundary-arn", required=True)
    parser.add_argument("--alert-kms-key-arn", required=True)
    parser.add_argument("--alb-allowed-cidr", required=True)
    parser.add_argument("--access-mode", choices=("https_token", "http_cidr_only"), required=True)
    parser.add_argument("--acm-certificate-arn", default="")
    parser.add_argument("--prediction-token-ssm-arn", default="")
    parser.add_argument("--api-image-ref", default="")
    parser.add_argument("--dashboard-image-ref", default="")
    parser.add_argument("--monitor-image-ref", default="")
    parser.add_argument("--active-pointer-file", type=Path)
    parser.add_argument("--budget-prerequisite-verified", action="store_true")
    parser.add_argument("--runtime-verification-file", type=Path)
    parser.add_argument("--source-commit", default="")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        stage = cast(Literal["prerequisites", "activation"], args.stage)
        access_mode = cast(Literal["https_token", "http_cidr_only"], args.access_mode)
        governance_mode = cast(Literal["team_protected", "solo_portfolio"], args.governance_mode)
        render_inputs(
            output_dir=args.output_dir,
            stage=stage,
            account_id=args.account_id,
            region=args.region,
            owner_tag=args.owner_tag,
            governance_mode=governance_mode,
            auto_destroy_date=args.auto_destroy_date,
            backend_bucket=args.backend_bucket,
            backend_kms_key_arn=args.backend_kms_key_arn,
            permission_boundary_arn=args.permission_boundary_arn,
            alert_kms_key_arn=args.alert_kms_key_arn,
            alb_allowed_cidr=args.alb_allowed_cidr,
            access_mode=access_mode,
            acm_certificate_arn=_optional(args.acm_certificate_arn),
            prediction_token_ssm_arn=_optional(args.prediction_token_ssm_arn),
            image_refs={
                "api": _optional(args.api_image_ref),
                "dashboard": _optional(args.dashboard_image_ref),
                "monitor": _optional(args.monitor_image_ref),
            },
            active_pointer=_load_pointer(args.active_pointer_file),
            budget_prerequisite_verified=args.budget_prerequisite_verified,
            runtime_verification=_load_runtime_verification(args.runtime_verification_file),
            source_commit=_optional(args.source_commit),
        )
        print(json.dumps({"status": "passed", "stage": stage}))
        return 0
    except (OSError, json.JSONDecodeError, ValidationError, RenderInputError) as error:
        reason = str(error).splitlines()[0][:160]
        print(json.dumps({"status": "refused", "reason": reason}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
