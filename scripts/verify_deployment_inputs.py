#!/usr/bin/env python3
"""Verify non-secret model-pointer, token metadata, and certificate deployment inputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlparse

from pydantic import ValidationError

from scripts.terraform_demo_guard import ActivePointer


class DeploymentInputError(RuntimeError):
    """A safe input-verification refusal reason."""


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DeploymentInputError("json_root_not_object")
    return value


def _parameter_value(response: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    parameter = response.get("Parameter")
    if not isinstance(parameter, dict):
        raise DeploymentInputError("active_pointer_parameter_missing")
    name = parameter.get("Name")
    value = parameter.get("Value")
    parameter_type = parameter.get("Type")
    if name != "/modelguard-ai/demo/models/active" or parameter_type != "String":
        raise DeploymentInputError("active_pointer_parameter_identity_invalid")
    if not isinstance(value, str):
        raise DeploymentInputError("active_pointer_value_missing")
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise DeploymentInputError("active_pointer_value_not_object")
    return name, parsed


def _certificate_covers_host(certificate: dict[str, Any], hostname: str) -> bool:
    names = certificate.get("SubjectAlternativeNames", [])
    domain = certificate.get("DomainName")
    if not isinstance(names, list):
        raise DeploymentInputError("certificate_san_list_invalid")
    candidates = [name for name in [domain, *names] if isinstance(name, str)]
    for candidate in candidates:
        normalized = candidate.casefold().rstrip(".")
        wanted = hostname.casefold().rstrip(".")
        if normalized == wanted:
            return True
        if normalized.startswith("*."):
            suffix = normalized[1:]
            if wanted.endswith(suffix) and wanted.count(".") == normalized.count("."):
                return True
    return False


def verify_inputs(
    *,
    pointer_response: dict[str, Any],
    account_id: str,
    region: str,
    model_version: str,
    manifest_sha256: str,
    access_mode: Literal["https_token", "http_cidr_only"],
    smoke_base_url: str,
    token_metadata: dict[str, Any] | None = None,
    token_parameter_arn: str | None = None,
    certificate_metadata: dict[str, Any] | None = None,
    certificate_arn: str | None = None,
) -> tuple[ActivePointer, dict[str, Any]]:
    """Verify exact pointer/model identity and metadata-only HTTPS prerequisites."""

    _, pointer_payload = _parameter_value(pointer_response)
    pointer = ActivePointer.model_validate(pointer_payload)
    target = pointer.target_identity
    expected_bucket = f"modelguard-ai-demo-{account_id}-{region}-models"
    if (
        target.get("model_version") != model_version
        or target.get("bundle_manifest_sha256") != manifest_sha256
        or pointer.bundle.get("bucket") != expected_bucket
    ):
        raise DeploymentInputError("active_pointer_model_identity_mismatch")
    parsed_url = urlparse(smoke_base_url)
    expected_scheme = "https" if access_mode == "https_token" else "http"
    expected_port = 443 if access_mode == "https_token" else 80
    try:
        configured_port = parsed_url.port
    except ValueError as error:
        raise DeploymentInputError("smoke_base_url_port_invalid") from error
    if (
        parsed_url.scheme != expected_scheme
        or not parsed_url.hostname
        or parsed_url.path not in ("", "/")
        or parsed_url.params
        or parsed_url.query
        or parsed_url.fragment
        or parsed_url.username is not None
        or parsed_url.password is not None
        or configured_port not in (None, expected_port)
    ):
        raise DeploymentInputError("smoke_base_url_identity_invalid")

    token_summary: dict[str, Any] | None = None
    certificate_summary: dict[str, Any] | None = None
    if access_mode == "https_token":
        if token_metadata is None or token_parameter_arn is None:
            raise DeploymentInputError("https_token_metadata_missing")
        expected_arn_prefix = (
            f"arn:aws:ssm:{region}:{account_id}:parameter/modelguard-ai/demo/secrets/"
        )
        if not token_parameter_arn.startswith(expected_arn_prefix):
            raise DeploymentInputError("token_parameter_arn_invalid")
        parameters = token_metadata.get("Parameters")
        expected_name = token_parameter_arn.split(":parameter", maxsplit=1)[1]
        if (
            not isinstance(parameters, list)
            or len(parameters) != 1
            or not isinstance(parameters[0], dict)
        ):
            raise DeploymentInputError("token_parameter_metadata_count_invalid")
        token = parameters[0]
        if (
            token.get("Name") != expected_name
            or token.get("Type") != "SecureString"
            or token.get("KeyId") != "alias/aws/ssm"
        ):
            raise DeploymentInputError("token_parameter_metadata_invalid")
        token_summary = {
            "arn": token_parameter_arn,
            "key_id": "alias/aws/ssm",
            "type": "SecureString",
            "value_fetched": False,
        }
        if certificate_metadata is None or certificate_arn is None:
            raise DeploymentInputError("https_certificate_metadata_missing")
        certificate = certificate_metadata.get("Certificate")
        if not isinstance(certificate, dict):
            raise DeploymentInputError("certificate_metadata_invalid")
        if (
            certificate.get("CertificateArn") != certificate_arn
            or certificate.get("Status") != "ISSUED"
            or not _certificate_covers_host(certificate, parsed_url.hostname)
        ):
            raise DeploymentInputError("certificate_identity_or_hostname_invalid")
        certificate_summary = {
            "arn": certificate_arn,
            "hostname": parsed_url.hostname,
            "status": "ISSUED",
        }
    elif any(
        value is not None
        for value in (token_metadata, token_parameter_arn, certificate_metadata, certificate_arn)
    ):
        raise DeploymentInputError("http_cidr_only_forbids_token_or_certificate")

    summary = {
        "schema_version": "modelguard.verified-deployment-inputs.v1",
        "account_id": account_id,
        "region": region,
        "access_mode": access_mode,
        "smoke_base_url": smoke_base_url,
        "model": {
            "version": model_version,
            "manifest_sha256": manifest_sha256,
            "bucket": expected_bucket,
            "bundle_prefix": pointer.bundle["key_prefix"],
            "object_count": len(pointer.bundle["object_version_ids"]),
        },
        "token": token_summary,
        "certificate": certificate_summary,
    }
    return pointer, summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="verify-deployment-inputs")
    parser.add_argument("--pointer-response", type=Path, required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--access-mode", choices=("https_token", "http_cidr_only"), required=True)
    parser.add_argument("--smoke-base-url", required=True)
    parser.add_argument("--token-metadata", type=Path)
    parser.add_argument("--token-parameter-arn")
    parser.add_argument("--certificate-metadata", type=Path)
    parser.add_argument("--certificate-arn")
    parser.add_argument("--output-pointer", type=Path, required=True)
    parser.add_argument("--output-summary", type=Path, required=True)
    parser.add_argument("--output-objects", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        access_mode = cast(Literal["https_token", "http_cidr_only"], args.access_mode)
        pointer, summary = verify_inputs(
            pointer_response=_load_object(args.pointer_response),
            account_id=args.account_id,
            region=args.region,
            model_version=args.model_version,
            manifest_sha256=args.manifest_sha256,
            access_mode=access_mode,
            smoke_base_url=args.smoke_base_url,
            token_metadata=_load_object(args.token_metadata) if args.token_metadata else None,
            token_parameter_arn=args.token_parameter_arn,
            certificate_metadata=(
                _load_object(args.certificate_metadata) if args.certificate_metadata else None
            ),
            certificate_arn=args.certificate_arn,
        )
        for output in (args.output_pointer, args.output_summary, args.output_objects):
            output.parent.mkdir(parents=True, exist_ok=True)
        args.output_pointer.write_text(
            json.dumps(pointer.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        args.output_summary.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        objects = [
            {
                "bucket": pointer.bundle["bucket"],
                "key": f"{pointer.bundle['key_prefix']}{filename}",
                "version_id": version_id,
            }
            for filename, version_id in sorted(pointer.bundle["object_version_ids"].items())
        ]
        args.output_objects.write_text(
            json.dumps(objects, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps({"status": "passed", "objects": len(objects)}))
        return 0
    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
        DeploymentInputError,
        KeyError,
    ) as error:
        reason = str(error).splitlines()[0][:180]
        print(json.dumps({"status": "refused", "reason": reason}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
