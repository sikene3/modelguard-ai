#!/usr/bin/env python3
"""Render a Terraform saved plan as action-only, value-free review evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from scripts.terraform_demo_guard import PlanManifest


class PlanEvidenceError(RuntimeError):
    """A safe plan-evidence refusal reason."""


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PlanEvidenceError("json_root_not_object")
    return value


def _safe_identifier(value: Any, *, field: str, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise PlanEvidenceError(f"plan_{field}_invalid")
    if re.fullmatch(r"[A-Za-z0-9_./\[\]\"-]+", value) is None:
        raise PlanEvidenceError(f"plan_{field}_unsafe")
    return value


def _safe_actions(value: Any) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(action, str) and re.fullmatch(r"[a-z-]+", action) for action in value)
    ):
        raise PlanEvidenceError("plan_change_actions_invalid")
    return value


def summarize_plan(
    plan: dict[str, Any],
    manifest: PlanManifest,
    *,
    repository: str,
    run_id: str,
    run_attempt: str,
    workflow_ref: str,
) -> dict[str, Any]:
    """Keep only resource addresses/actions and sealed non-secret identity metadata."""

    raw_changes = plan.get("resource_changes", [])
    if not isinstance(raw_changes, list):
        raise PlanEvidenceError("plan_resource_changes_not_array")
    changes: list[dict[str, Any]] = []
    action_counts: Counter[str] = Counter()
    for raw_change in raw_changes:
        if not isinstance(raw_change, dict):
            raise PlanEvidenceError("plan_resource_change_not_object")
        change = raw_change.get("change")
        if not isinstance(change, dict):
            raise PlanEvidenceError("plan_change_invalid")
        actions = _safe_actions(change.get("actions"))
        action_key = "/".join(actions)
        action_counts[action_key] += 1
        changes.append(
            {
                "address": _safe_identifier(raw_change.get("address"), field="address"),
                "actions": actions,
                "provider": _safe_identifier(
                    raw_change.get("provider_name", "unknown"), field="provider"
                ),
                "resource_type": _safe_identifier(raw_change.get("type"), field="resource_type"),
            }
        )
    output_changes = plan.get("output_changes", {})
    if not isinstance(output_changes, dict):
        raise PlanEvidenceError("plan_output_changes_not_object")
    outputs: list[dict[str, Any]] = []
    for name, raw_output in sorted(output_changes.items()):
        if not isinstance(raw_output, dict):
            raise PlanEvidenceError("plan_output_change_invalid")
        outputs.append(
            {
                "name": _safe_identifier(name, field="output_name"),
                "actions": _safe_actions(raw_output.get("actions")),
                "sensitive": bool(raw_output.get("after_sensitive", False)),
            }
        )
    masked_account = f"********{manifest.account_id[-4:]}"
    return {
        "schema_version": "modelguard.redacted-terraform-plan.v1",
        "redaction": (
            "all before/after values, configuration, variables, and sensitive payloads omitted"
        ),
        "identity": {
            "account_id_masked": masked_account,
            "activate_services": manifest.activate_services,
            "auto_destroy_date": manifest.auto_destroy_date.isoformat(),
            "backend_config_sha256": manifest.backend_config_sha256,
            "git_commit": manifest.git_commit,
            "plan_sha256": manifest.plan_sha256,
            "project": manifest.project,
            "region": manifest.region,
            "sealed_at": manifest.sealed_at.isoformat(),
            "stage": manifest.stage,
            "variable_file_sha256": manifest.variable_file_sha256,
            "workspace": manifest.workspace,
        },
        "workflow": {
            "repository": repository,
            "run_attempt": run_attempt,
            "run_id": run_id,
            "workflow_ref": workflow_ref,
        },
        "terraform": {
            "format_version": str(plan.get("format_version", "unknown")),
            "terraform_version": str(plan.get("terraform_version", "unknown")),
        },
        "action_counts": dict(sorted(action_counts.items())),
        "resource_changes": sorted(changes, key=lambda item: item["address"]),
        "output_changes": outputs,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    """Render one concise human review document without Terraform values."""

    identity = summary["identity"]
    lines = [
        f"# Redacted Terraform {identity['stage']} plan",
        "",
        (
            "> Values are intentionally omitted. The raw saved plan is restricted to "
            "same-run transfer."
        ),
        "",
        "## Sealed identity",
        "",
        f"- Source commit: `{identity['git_commit']}`",
        f"- Plan SHA-256: `{identity['plan_sha256']}`",
        f"- AWS account / Region: `{identity['account_id_masked']}` / `{identity['region']}`",
        f"- Backend configuration SHA-256: `{identity['backend_config_sha256']}`",
        f"- Workspace: `{identity['workspace']}`",
        f"- Runtime activation: `{str(identity['activate_services']).lower()}`",
        f"- AutoDestroyDate: `{identity['auto_destroy_date']}`",
        "",
        "## Action counts",
        "",
    ]
    counts = summary["action_counts"]
    if counts:
        lines.extend(f"- `{action}`: {count}" for action, count in counts.items())
    else:
        lines.append("- No resource changes.")
    lines.extend(["", "## Resource actions", ""])
    changes = summary["resource_changes"]
    if changes:
        lines.extend(f"- `{'/'.join(item['actions'])}` `{item['address']}`" for item in changes)
    else:
        lines.append("- No resource changes.")
    lines.append("")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plan-evidence")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--workflow-ref", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        raw_plan = json.load(sys.stdin)
        if not isinstance(raw_plan, dict):
            raise PlanEvidenceError("plan_json_root_not_object")
        manifest = PlanManifest.model_validate(_load_object(args.manifest))
        summary = summarize_plan(
            raw_plan,
            manifest,
            repository=args.repository,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            workflow_ref=args.workflow_ref,
        )
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        args.output_markdown.write_text(render_markdown(summary), encoding="utf-8")
        print(json.dumps({"status": "passed", "resources": len(summary["resource_changes"])}))
        return 0
    except (OSError, json.JSONDecodeError, ValidationError, PlanEvidenceError) as error:
        reason = str(error).splitlines()[0][:160]
        print(json.dumps({"status": "refused", "reason": reason}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
