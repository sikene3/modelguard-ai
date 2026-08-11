#!/usr/bin/env python3
"""Render a Terraform saved plan as action-only, value-free review evidence."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import tempfile
from collections import Counter
from contextlib import suppress
from pathlib import Path
from typing import Any, TextIO

from scripts.terraform_demo_guard import GuardError, PlanManifest, load_plan_manifest


class PlanEvidenceError(RuntimeError):
    """A safe plan-evidence refusal reason."""


AWS_PROVIDER = "registry.terraform.io/hashicorp/aws"
TERRAFORM_PROVIDER = "terraform.io/builtin/terraform"
DEPOSED_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
REQUIRED_TAGGED_BASES = frozenset(
    {
        "aws_cloudwatch_log_group.application",
        "aws_cloudwatch_log_group.firehose",
        "aws_cloudwatch_metric_alarm.alb_api_5xx",
        "aws_cloudwatch_metric_alarm.alb_api_latency",
        "aws_cloudwatch_metric_alarm.alb_healthy_hosts",
        "aws_cloudwatch_metric_alarm.api_event_write_failures",
        "aws_cloudwatch_metric_alarm.firehose_delivery",
        "aws_cloudwatch_metric_alarm.monitor_completion",
        "aws_cloudwatch_metric_alarm.monitor_input",
        "aws_cloudwatch_metric_alarm.monitor_predictions",
        "aws_cloudwatch_metric_alarm.monitor_rejected",
        "aws_cloudwatch_metric_alarm.monitor_report_freshness",
        "aws_cloudwatch_metric_alarm.scheduler_submission_failures",
        "aws_ecs_cluster.this",
        "aws_ecs_task_definition.monitor",
        "aws_iam_role.api",
        "aws_iam_role.dashboard",
        "aws_iam_role.ecs_execution",
        "aws_iam_role.firehose",
        "aws_iam_role.monitor",
        "aws_iam_role.scheduler",
        "aws_kinesis_firehose_delivery_stream.predictions",
        "aws_lb.this",
        "aws_lb_listener.http_demo",
        "aws_lb_listener.http_redirect",
        "aws_lb_listener.https",
        "aws_lb_listener_rule.api",
        "aws_lb_listener_rule.block_metrics",
        "aws_lb_target_group.api",
        "aws_lb_target_group.dashboard",
        "aws_scheduler_schedule_group.monitor",
        "aws_sns_topic.alerts",
        "aws_ssm_parameter.active_model",
        "aws_ssm_parameter.previous_model",
        "module.api_service.aws_ecs_service.this",
        "module.api_service.aws_ecs_task_definition.this",
        "module.dashboard_service.aws_ecs_service.this",
        "module.dashboard_service.aws_ecs_task_definition.this",
        "module.data_plane.aws_ecr_repository.this",
        "module.data_plane.aws_s3_bucket.this",
        "module.network.aws_default_security_group.restricted",
        "module.network.aws_eip.nat",
        "module.network.aws_internet_gateway.this",
        "module.network.aws_nat_gateway.this",
        "module.network.aws_route_table.private",
        "module.network.aws_route_table.public",
        "module.network.aws_security_group.alb",
        "module.network.aws_security_group.api",
        "module.network.aws_security_group.dashboard",
        "module.network.aws_security_group.monitor",
        "module.network.aws_subnet.private",
        "module.network.aws_subnet.public",
        "module.network.aws_vpc.this",
        "module.network.aws_vpc_endpoint.s3",
        "module.network.aws_vpc_security_group_egress_rule.alb_to_api",
        "module.network.aws_vpc_security_group_egress_rule.alb_to_dashboard",
        "module.network.aws_vpc_security_group_egress_rule.task_dns_tcp",
        "module.network.aws_vpc_security_group_egress_rule.task_dns_udp",
        "module.network.aws_vpc_security_group_egress_rule.task_https",
        "module.network.aws_vpc_security_group_ingress_rule.alb_http",
        "module.network.aws_vpc_security_group_ingress_rule.alb_https",
        "module.network.aws_vpc_security_group_ingress_rule.api_from_alb",
        "module.network.aws_vpc_security_group_ingress_rule.dashboard_from_alb",
    }
)
TASK_DEFINITION_ADDRESSES = {
    "aws_ecs_task_definition.monitor": "monitor",
    "module.api_service.aws_ecs_task_definition.this": "api",
    "module.dashboard_service.aws_ecs_task_definition.this": "dashboard",
}
ECS_SERVICE_ADDRESSES = {
    "module.api_service.aws_ecs_service.this": "api",
    "module.dashboard_service.aws_ecs_service.this": "dashboard",
}
ALARM_ADDRESSES = frozenset(
    {
        "aws_cloudwatch_metric_alarm.alb_api_5xx",
        "aws_cloudwatch_metric_alarm.alb_api_latency",
        'aws_cloudwatch_metric_alarm.alb_healthy_hosts["api"]',
        'aws_cloudwatch_metric_alarm.alb_healthy_hosts["dashboard"]',
        "aws_cloudwatch_metric_alarm.api_event_write_failures",
        "aws_cloudwatch_metric_alarm.firehose_delivery",
        "aws_cloudwatch_metric_alarm.monitor_completion",
        "aws_cloudwatch_metric_alarm.monitor_input",
        "aws_cloudwatch_metric_alarm.monitor_predictions",
        "aws_cloudwatch_metric_alarm.monitor_rejected",
        "aws_cloudwatch_metric_alarm.monitor_report_freshness",
        "aws_cloudwatch_metric_alarm.scheduler_submission_failures",
    }
)
ACTIVATION_UPDATE_ADDRESSES = frozenset(
    {
        *ECS_SERVICE_ADDRESSES,
        *ALARM_ADDRESSES,
        "aws_iam_role_policy.scheduler",
        "aws_scheduler_schedule.monitor",
        "terraform_data.deployment_guard",
    }
)
ALLOWED_OUTPUTS = frozenset(
    {
        "activation_state",
        "alert_topic_arn",
        "alb_url",
        "data_bucket_names",
        "deployment_governance_mode",
        "ecr_repository_urls",
        "ecs_cluster_arn",
        "manual_budget_contract",
        "model_pointer_names",
        "post_destroy_inventory_identity",
        "task_definition_arns",
        "workload_role_arns",
    }
)


def _resource_bases() -> dict[str, str]:
    grouped: dict[str, tuple[str, ...]] = {
        "aws_cloudwatch_log_group": ("application", "firehose"),
        "aws_cloudwatch_log_stream": ("firehose",),
        "aws_cloudwatch_metric_alarm": (
            "alb_api_5xx",
            "alb_api_latency",
            "alb_healthy_hosts",
            "api_event_write_failures",
            "firehose_delivery",
            "monitor_completion",
            "monitor_input",
            "monitor_predictions",
            "monitor_rejected",
            "monitor_report_freshness",
            "scheduler_submission_failures",
        ),
        "aws_ecs_cluster": ("this",),
        "aws_ecs_task_definition": ("monitor",),
        "aws_iam_role": ("api", "dashboard", "ecs_execution", "firehose", "monitor", "scheduler"),
        "aws_iam_role_policy": (
            "api",
            "dashboard",
            "ecs_execution",
            "firehose",
            "monitor",
            "scheduler",
        ),
        "aws_kinesis_firehose_delivery_stream": ("predictions",),
        "aws_lb": ("this",),
        "aws_lb_listener": ("http_demo", "http_redirect", "https"),
        "aws_lb_listener_rule": ("api", "block_metrics"),
        "aws_lb_target_group": ("api", "dashboard"),
        "aws_scheduler_schedule": ("monitor",),
        "aws_scheduler_schedule_group": ("monitor",),
        "aws_sns_topic": ("alerts",),
        "aws_sns_topic_policy": ("alerts",),
        "aws_ssm_parameter": ("active_model", "previous_model"),
        "terraform_data": ("deployment_guard",),
    }
    result = {
        f"{resource_type}.{name}": resource_type
        for resource_type, names in grouped.items()
        for name in names
    }
    module_types: dict[str, dict[str, tuple[str, ...]]] = {
        "module.api_service": {
            "aws_ecs_service": ("this",),
            "aws_ecs_task_definition": ("this",),
        },
        "module.dashboard_service": {
            "aws_ecs_service": ("this",),
            "aws_ecs_task_definition": ("this",),
        },
        "module.data_plane": {
            "aws_ecr_lifecycle_policy": ("this",),
            "aws_ecr_repository": ("this",),
            "aws_s3_bucket": ("this",),
            "aws_s3_bucket_lifecycle_configuration": ("this",),
            "aws_s3_bucket_logging": ("this",),
            "aws_s3_bucket_ownership_controls": ("this",),
            "aws_s3_bucket_policy": ("this",),
            "aws_s3_bucket_public_access_block": ("this",),
            "aws_s3_bucket_server_side_encryption_configuration": ("this",),
            "aws_s3_bucket_versioning": ("this",),
        },
        "module.network": {
            "aws_default_security_group": ("restricted",),
            "aws_eip": ("nat",),
            "aws_internet_gateway": ("this",),
            "aws_nat_gateway": ("this",),
            "aws_route": ("private_ipv4", "public_ipv4"),
            "aws_route_table": ("private", "public"),
            "aws_route_table_association": ("private", "public"),
            "aws_security_group": ("alb", "api", "dashboard", "monitor"),
            "aws_subnet": ("private", "public"),
            "aws_vpc": ("this",),
            "aws_vpc_endpoint": ("s3",),
            "aws_vpc_security_group_egress_rule": (
                "alb_to_api",
                "alb_to_dashboard",
                "task_dns_tcp",
                "task_dns_udp",
                "task_https",
            ),
            "aws_vpc_security_group_ingress_rule": (
                "alb_http",
                "alb_https",
                "api_from_alb",
                "dashboard_from_alb",
            ),
        },
    }
    for module, resources in module_types.items():
        for resource_type, names in resources.items():
            for name in names:
                result[f"{module}.{resource_type}.{name}"] = resource_type
    return result


MANAGED_RESOURCE_BASES = _resource_bases()
DATA_RESOURCE_BASES = {
    "data.aws_caller_identity.current": "aws_caller_identity",
    "data.aws_iam_policy_document.alert_topic": "aws_iam_policy_document",
    "data.aws_iam_policy_document.api": "aws_iam_policy_document",
    "data.aws_iam_policy_document.dashboard": "aws_iam_policy_document",
    "data.aws_iam_policy_document.ecs_execution": "aws_iam_policy_document",
    "data.aws_iam_policy_document.ecs_task_trust": "aws_iam_policy_document",
    "data.aws_iam_policy_document.firehose": "aws_iam_policy_document",
    "data.aws_iam_policy_document.firehose_trust": "aws_iam_policy_document",
    "data.aws_iam_policy_document.monitor": "aws_iam_policy_document",
    "data.aws_iam_policy_document.scheduler": "aws_iam_policy_document",
    "data.aws_iam_policy_document.scheduler_trust": "aws_iam_policy_document",
    "data.aws_partition.current": "aws_partition",
    "data.aws_region.current": "aws_region",
    "data.aws_ssm_parameter.active_current": "aws_ssm_parameter",
    "module.data_plane.data.aws_iam_policy_document.bucket": "aws_iam_policy_document",
    "module.data_plane.data.aws_partition.current": "aws_partition",
    "module.network.data.aws_partition.current": "aws_partition",
    "module.network.data.aws_region.current": "aws_region",
}

INDEXED_MANAGED_KEYS: dict[str, tuple[str | int, ...]] = {
    "aws_cloudwatch_log_group.application": ("api", "dashboard", "monitor"),
    "aws_cloudwatch_metric_alarm.alb_healthy_hosts": ("api", "dashboard"),
    "aws_lb_listener.http_demo": (0,),
    "aws_lb_listener.http_redirect": (0,),
    "aws_lb_listener.https": (0,),
    "module.data_plane.aws_ecr_lifecycle_policy.this": ("api", "dashboard", "monitor"),
    "module.data_plane.aws_ecr_repository.this": ("api", "dashboard", "monitor"),
    "module.data_plane.aws_s3_bucket.this": ("audit", "models", "predictions", "reports"),
    "module.data_plane.aws_s3_bucket_lifecycle_configuration.this": (
        "audit",
        "models",
        "predictions",
        "reports",
    ),
    "module.data_plane.aws_s3_bucket_logging.this": ("models", "predictions", "reports"),
    "module.data_plane.aws_s3_bucket_ownership_controls.this": (
        "audit",
        "models",
        "predictions",
        "reports",
    ),
    "module.data_plane.aws_s3_bucket_policy.this": (
        "audit",
        "models",
        "predictions",
        "reports",
    ),
    "module.data_plane.aws_s3_bucket_public_access_block.this": (
        "audit",
        "models",
        "predictions",
        "reports",
    ),
    "module.data_plane.aws_s3_bucket_server_side_encryption_configuration.this": (
        "audit",
        "models",
        "predictions",
        "reports",
    ),
    "module.data_plane.aws_s3_bucket_versioning.this": (
        "audit",
        "models",
        "predictions",
        "reports",
    ),
    "module.network.aws_vpc_security_group_egress_rule.task_dns_tcp": (
        "api",
        "dashboard",
        "monitor",
    ),
    "module.network.aws_vpc_security_group_egress_rule.task_dns_udp": (
        "api",
        "dashboard",
        "monitor",
    ),
    "module.network.aws_vpc_security_group_egress_rule.task_https": (
        "api",
        "dashboard",
        "monitor",
    ),
    "module.network.aws_vpc_security_group_ingress_rule.alb_https": (0,),
}
INDEXED_DATA_KEYS: dict[str, tuple[str | int, ...]] = {
    "data.aws_ssm_parameter.active_current": (0,),
    "module.data_plane.data.aws_iam_policy_document.bucket": (
        "audit",
        "models",
        "predictions",
        "reports",
    ),
}


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


def _instance_base(address: str) -> str:
    match = re.fullmatch(
        r'(?P<base>[A-Za-z0-9_.-]+)(?:\[(?:[0-9]+|"[A-Za-z0-9_.-]+")\])?',
        address,
    )
    if match is None:
        raise PlanEvidenceError("plan_address_not_allowlisted")
    return match.group("base")


def _concrete_address(base: str, key: str | int) -> str:
    return f"{base}[{key}]" if isinstance(key, int) else f'{base}["{key}"]'


def _allowed_resource_addresses(manifest: PlanManifest, *, mode: str) -> dict[str, str]:
    bases = DATA_RESOURCE_BASES if mode == "data" else MANAGED_RESOURCE_BASES
    indexed_keys = dict(INDEXED_DATA_KEYS if mode == "data" else INDEXED_MANAGED_KEYS)
    if mode == "managed":
        zones = (f"{manifest.region}a", f"{manifest.region}b")
        for name in ("private", "public"):
            indexed_keys[f"module.network.aws_subnet.{name}"] = zones
            indexed_keys[f"module.network.aws_route_table_association.{name}"] = zones
    result: dict[str, str] = {}
    for base, resource_type in bases.items():
        keys = indexed_keys.get(base)
        if keys is None:
            result[base] = resource_type
        else:
            for key in keys:
                result[_concrete_address(base, key)] = resource_type
    return result


def _validate_actions(
    actions: list[str],
    *,
    stage: str,
    mode: str,
    address: str,
) -> None:
    action_tuple = tuple(actions)
    if mode == "data":
        if action_tuple not in {("no-op",), ("read",)}:
            raise PlanEvidenceError("plan_data_action_forbidden")
        return
    if stage == "destroy":
        if action_tuple != ("delete",):
            raise PlanEvidenceError("plan_destroy_action_forbidden")
        return
    if stage == "prerequisites":
        if action_tuple not in {("create",), ("no-op",)}:
            if "delete" in action_tuple:
                raise PlanEvidenceError("plan_non_destroy_delete_forbidden")
            raise PlanEvidenceError("plan_prerequisite_action_forbidden")
        return
    if action_tuple == ("no-op",):
        return
    if action_tuple == ("update",) and address in ACTIVATION_UPDATE_ADDRESSES:
        return
    if action_tuple in {("create", "delete"), ("delete", "create")} and (
        address in TASK_DEFINITION_ADDRESSES
    ):
        return
    if "delete" in action_tuple:
        raise PlanEvidenceError("plan_non_destroy_delete_forbidden")
    raise PlanEvidenceError("plan_activation_action_forbidden")


def _validate_output_actions(actions: list[str], *, stage: str) -> None:
    allowed = {
        "prerequisites": {("create",), ("no-op",)},
        "activation": {("update",), ("no-op",)},
        "destroy": {("delete",), ("no-op",)},
    }
    if tuple(actions) not in allowed[stage]:
        raise PlanEvidenceError("plan_output_action_forbidden")


def _validate_tags(change: dict[str, Any], manifest: PlanManifest) -> None:
    values = change.get("before" if manifest.stage == "destroy" else "after")
    if not isinstance(values, dict):
        raise PlanEvidenceError("plan_required_tags_missing")
    tags = values.get("tags_all")
    if not isinstance(tags, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in tags.items()
    ):
        raise PlanEvidenceError("plan_required_tags_missing")
    required = {
        "AutoDestroyDate": manifest.auto_destroy_date.isoformat(),
        "Environment": manifest.environment,
        "ManagedBy": "Terraform",
        "Owner": manifest.owner_tag,
        "Ownership": "demo",
        "Project": manifest.project,
    }
    if any(tags.get(key) != value for key, value in required.items()):
        raise PlanEvidenceError("plan_required_tags_mismatch")


def _validate_workflow_identity(
    *, repository: str, run_id: str, run_attempt: str, workflow_ref: str
) -> None:
    if (repository, run_id, run_attempt, workflow_ref) == (
        "local/operator",
        "human",
        "1",
        "local/operator",
    ):
        return
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        raise PlanEvidenceError("workflow_repository_invalid")
    if re.fullmatch(r"[1-9][0-9]*", run_id) is None:
        raise PlanEvidenceError("workflow_run_id_invalid")
    if re.fullmatch(r"[1-9][0-9]*", run_attempt) is None:
        raise PlanEvidenceError("workflow_run_attempt_invalid")
    if (
        len(workflow_ref) > 500
        or re.fullmatch(r"[A-Za-z0-9_./@-]+", workflow_ref) is None
        or not workflow_ref.startswith(f"{repository}/.github/workflows/")
    ):
        raise PlanEvidenceError("workflow_ref_invalid")


def _strict_plan_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PlanEvidenceError("plan_json_duplicate_key")
        value[key] = item
    return value


def _reject_plan_constant(_: str) -> None:
    raise PlanEvidenceError("plan_json_non_finite_number")


def load_terraform_show_json(stream: TextIO) -> dict[str, Any]:
    """Load Terraform show JSON without accepting duplicate keys or non-finite numbers."""

    try:
        value = json.load(
            stream,
            object_pairs_hook=_strict_plan_pairs,
            parse_constant=_reject_plan_constant,
        )
    except json.JSONDecodeError as error:
        raise PlanEvidenceError("plan_json_invalid") from error
    if not isinstance(value, dict):
        raise PlanEvidenceError("plan_json_root_not_object")
    return value


def _after_values(changes: dict[str, dict[str, Any]], address: str) -> dict[str, Any]:
    change = changes.get(address)
    if not isinstance(change, dict):
        raise PlanEvidenceError("plan_stage_required_address_missing")
    after = change.get("after")
    if not isinstance(after, dict):
        raise PlanEvidenceError("plan_stage_after_values_missing")
    return after


def _provider_null_as_empty_list(value: Any) -> Any:
    """Normalize an optional Terraform provider collection without masking bad values."""
    return [] if value is None else value


def _before_values(changes: dict[str, dict[str, Any]], address: str) -> dict[str, Any]:
    change = changes.get(address)
    if not isinstance(change, dict):
        raise PlanEvidenceError("plan_destroy_source_address_missing")
    before = change.get("before")
    if not isinstance(before, dict):
        raise PlanEvidenceError("plan_destroy_source_values_missing")
    return before


def _parse_container_definitions(value: Any) -> list[Any]:
    if not isinstance(value, str) or not value or len(value) > 1024 * 1024:
        raise PlanEvidenceError("plan_task_container_contract_invalid")
    try:
        parsed = json.loads(
            value,
            object_pairs_hook=_strict_plan_pairs,
            parse_constant=_reject_plan_constant,
        )
    except json.JSONDecodeError as error:
        raise PlanEvidenceError("plan_task_container_contract_invalid") from error
    if not isinstance(parsed, list):
        raise PlanEvidenceError("plan_task_container_contract_invalid")
    return parsed


def _validate_stage_contract(
    changes: dict[str, dict[str, Any]], manifest: PlanManifest
) -> dict[str, bool]:
    if manifest.stage == "destroy":
        if (
            not manifest.teardown_authorized
            or manifest.activate_services
            or manifest.source_activation_state is None
        ):
            raise PlanEvidenceError("plan_destroy_authorization_invalid")

        critical_fields = {
            "module.api_service.aws_ecs_service.this": "desired_count",
            "module.dashboard_service.aws_ecs_service.this": "desired_count",
            "aws_scheduler_schedule.monitor": "state",
        }
        observed: dict[str, Any] = {}
        for address, field in critical_fields.items():
            if address not in changes:
                continue
            value = _before_values(changes, address).get(field)
            if field == "desired_count":
                valid = isinstance(value, int) and not isinstance(value, bool) and value >= 0
            else:
                valid = value in {"DISABLED", "ENABLED"}
            if not valid:
                raise PlanEvidenceError("plan_destroy_partial_state_invalid")
            observed[address] = value
        if observed == {
            "module.api_service.aws_ecs_service.this": 1,
            "module.dashboard_service.aws_ecs_service.this": 1,
            "aws_scheduler_schedule.monitor": "ENABLED",
        }:
            derived_state = "active"
        elif observed == {
            "module.api_service.aws_ecs_service.this": 0,
            "module.dashboard_service.aws_ecs_service.this": 0,
            "aws_scheduler_schedule.monitor": "DISABLED",
        }:
            derived_state = "dormant"
        else:
            derived_state = "mixed_or_partial"
        if manifest.source_activation_state != derived_state:
            raise PlanEvidenceError("plan_destroy_source_state_mismatch")

        guard_change = changes.get("terraform_data.deployment_guard")
        if guard_change is not None:
            guard_input = _before_values(changes, "terraform_data.deployment_guard").get("input")
            if (
                not isinstance(guard_input, dict)
                or set(guard_input)
                != {"deployment_governance_mode", "deployment_stage", "environment", "project"}
                or guard_input.get("deployment_governance_mode")
                != manifest.deployment_governance_mode
                or guard_input.get("deployment_stage") not in {"prerequisites", "activation"}
                or guard_input.get("environment") != manifest.environment
                or guard_input.get("project") != manifest.project
            ):
                raise PlanEvidenceError("plan_destroy_governance_state_mismatch")
        return {
            "destroy_action_boundary_verified": True,
            "destroy_source_activation_boundary_verified": True,
            "destroy_source_governance_boundary_verified": True,
            "teardown_authorization_verified": True,
        }

    desired_count = 1 if manifest.stage == "activation" else 0
    for address in ECS_SERVICE_ADDRESSES:
        value = _after_values(changes, address).get("desired_count")
        if not isinstance(value, int) or isinstance(value, bool) or value != desired_count:
            raise PlanEvidenceError("plan_ecs_desired_count_mismatch")

    schedule_state = "ENABLED" if manifest.stage == "activation" else "DISABLED"
    if _after_values(changes, "aws_scheduler_schedule.monitor").get("state") != schedule_state:
        raise PlanEvidenceError("plan_scheduler_state_mismatch")

    topic_arn = (
        f"arn:aws:sns:{manifest.region}:{manifest.account_id}:"
        f"{manifest.project}-{manifest.environment}-alerts"
    )
    expected_actions = [topic_arn] if manifest.stage == "activation" else []
    for address in ALARM_ADDRESSES:
        after = _after_values(changes, address)
        if after.get("actions_enabled") is not (manifest.stage == "activation"):
            raise PlanEvidenceError("plan_alarm_activation_mismatch")
        if (
            _provider_null_as_empty_list(after.get("alarm_actions")) != expected_actions
            or _provider_null_as_empty_list(after.get("ok_actions")) != expected_actions
            or _provider_null_as_empty_list(after.get("insufficient_data_actions")) != []
        ):
            raise PlanEvidenceError("plan_alarm_action_boundary_mismatch")

    attestations = {
        "alarm_action_boundary_verified": True,
        "required_stage_addresses_verified": True,
        "runtime_desired_counts_verified": True,
        "scheduler_state_verified": True,
    }
    if manifest.stage == "activation":
        for address, component in TASK_DEFINITION_ADDRESSES.items():
            after = _after_values(changes, address)
            definitions = _parse_container_definitions(after.get("container_definitions"))
            if len(definitions) != 1 or not isinstance(definitions[0], dict):
                raise PlanEvidenceError("plan_task_container_contract_invalid")
            container = definitions[0]
            image_ref = container.get("image")
            expected_prefix = (
                f"{manifest.account_id}.dkr.ecr.{manifest.region}.amazonaws.com/"
                f"{manifest.project}/{manifest.environment}/{component}@sha256:"
            )
            if (
                container.get("name") != component
                or not isinstance(image_ref, str)
                or not image_ref.startswith(expected_prefix)
                or re.fullmatch(re.escape(expected_prefix) + r"[0-9a-f]{64}", image_ref) is None
            ):
                raise PlanEvidenceError("plan_task_image_identity_mismatch")
        attestations["immutable_task_image_digests_verified"] = True
    return attestations


def verify_opaque_plan(plan_path: Path, manifest: PlanManifest) -> None:
    """Bind streamed Terraform JSON evidence to the exact opaque saved-plan bytes."""

    try:
        metadata = plan_path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise PlanEvidenceError("opaque_plan_not_regular")
        if metadata.st_uid != os.geteuid():
            raise PlanEvidenceError("opaque_plan_owner_invalid")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise PlanEvidenceError("opaque_plan_mode_invalid")
        if plan_path.name != manifest.plan_filename:
            raise PlanEvidenceError("opaque_plan_filename_mismatch")
        digest = hashlib.sha256()
        with plan_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise PlanEvidenceError("opaque_plan_unavailable") from error
    if not hmac.compare_digest(digest.hexdigest(), manifest.plan_sha256):
        raise PlanEvidenceError("opaque_plan_sha256_mismatch")


def write_evidence_file(path: Path, payload: str) -> None:
    """Atomically publish one create-only, regular, owner-only evidence file."""

    try:
        parent_metadata = path.parent.lstat()
    except OSError as error:
        raise PlanEvidenceError("evidence_output_parent_unavailable") from error
    if not stat.S_ISDIR(parent_metadata.st_mode) or stat.S_ISLNK(parent_metadata.st_mode):
        raise PlanEvidenceError("evidence_output_parent_not_directory")
    temporary_path: Path | None = None
    try:
        file_descriptor, raw_temporary_path = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(raw_temporary_path)
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(payload.encode("utf-8"))
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
        raise PlanEvidenceError("evidence_output_exists") from error
    except OSError as error:
        raise PlanEvidenceError("evidence_output_write_failed") from error
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
    try:
        metadata = path.lstat()
    except OSError as error:
        raise PlanEvidenceError("evidence_output_write_failed") from error
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise PlanEvidenceError("evidence_output_not_regular")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise PlanEvidenceError("evidence_output_mode_invalid")


def _validate_plan_status(plan: dict[str, Any], *, stage: str) -> None:
    if plan.get("errored", False) is not False:
        raise PlanEvidenceError("plan_errored")
    if "applyable" in plan and plan["applyable"] is not True:
        raise PlanEvidenceError("plan_not_applyable")
    if "complete" in plan and plan["complete"] is not True:
        raise PlanEvidenceError("plan_incomplete")
    drift = plan.get("resource_drift", [])
    if not isinstance(drift, list) or (stage not in {"prerequisites", "destroy"} and drift):
        raise PlanEvidenceError("plan_resource_drift_present")


def _validate_destroy_drift(plan: dict[str, Any], manifest: PlanManifest) -> list[dict[str, Any]]:
    raw_drift = plan.get("resource_drift", [])
    if not isinstance(raw_drift, list):
        raise PlanEvidenceError("plan_resource_drift_present")
    drift: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed = _allowed_resource_addresses(manifest, mode="managed")
    for raw_change in raw_drift:
        if not isinstance(raw_change, dict):
            raise PlanEvidenceError("plan_drift_change_invalid")
        address = _safe_identifier(raw_change.get("address"), field="drift_address")
        if address in seen:
            raise PlanEvidenceError("plan_drift_address_duplicate")
        seen.add(address)
        if raw_change.get("mode") != "managed" or "deposed" in raw_change:
            raise PlanEvidenceError("plan_drift_mode_invalid")
        resource_type = _safe_identifier(raw_change.get("type"), field="drift_resource_type")
        if allowed.get(address) != resource_type:
            if resource_type == "aws_budgets_budget" or resource_type.startswith("aws_budgets_"):
                raise PlanEvidenceError("plan_budget_resource_forbidden")
            raise PlanEvidenceError("plan_drift_resource_not_allowlisted")
        provider = _safe_identifier(raw_change.get("provider_name"), field="drift_provider")
        expected_provider = (
            TERRAFORM_PROVIDER if resource_type == "terraform_data" else AWS_PROVIDER
        )
        if provider != expected_provider:
            raise PlanEvidenceError("plan_drift_provider_mismatch")
        base = _instance_base(address)
        if base not in REQUIRED_TAGGED_BASES:
            raise PlanEvidenceError("plan_drift_ownership_unverifiable")
        change = raw_change.get("change")
        if not isinstance(change, dict):
            raise PlanEvidenceError("plan_drift_change_invalid")
        actions = _safe_actions(change.get("actions"))
        if tuple(actions) not in {
            ("create",),
            ("delete",),
            ("update",),
            ("create", "delete"),
            ("delete", "create"),
        }:
            raise PlanEvidenceError("plan_drift_action_forbidden")
        _validate_tags(change, manifest)
        drift.append(
            {
                "address": address,
                "actions": actions,
                "provider": provider,
                "resource_type": resource_type,
            }
        )
    return sorted(drift, key=lambda item: item["address"])


def _validate_prerequisite_recovery_drift(
    plan: dict[str, Any],
    manifest: PlanManifest,
    raw_changes: list[Any],
) -> list[dict[str, Any]]:
    """Allow only owned drift already equal to desired state during partial-apply recovery."""

    raw_drift = plan.get("resource_drift", [])
    if not isinstance(raw_drift, list):
        raise PlanEvidenceError("plan_resource_drift_present")
    if not raw_drift:
        return []

    changes_by_address: dict[str, dict[str, Any]] = {}
    managed_actions: list[tuple[str, ...]] = []
    for raw_change in raw_changes:
        if not isinstance(raw_change, dict):
            raise PlanEvidenceError("plan_resource_change_not_object")
        address = _safe_identifier(raw_change.get("address"), field="address")
        if address in changes_by_address or "deposed" in raw_change:
            raise PlanEvidenceError("plan_recovery_drift_change_identity_invalid")
        changes_by_address[address] = raw_change
        change = raw_change.get("change")
        if raw_change.get("mode") == "managed" and isinstance(change, dict):
            managed_actions.append(tuple(_safe_actions(change.get("actions"))))
    if ("create",) not in managed_actions or ("no-op",) not in managed_actions:
        raise PlanEvidenceError("plan_recovery_drift_stage_shape_invalid")

    drift: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed = _allowed_resource_addresses(manifest, mode="managed")
    for raw_change in raw_drift:
        if not isinstance(raw_change, dict):
            raise PlanEvidenceError("plan_drift_change_invalid")
        address = _safe_identifier(raw_change.get("address"), field="drift_address")
        if address in seen:
            raise PlanEvidenceError("plan_drift_address_duplicate")
        seen.add(address)
        if raw_change.get("mode") != "managed" or "deposed" in raw_change:
            raise PlanEvidenceError("plan_drift_mode_invalid")
        resource_type = _safe_identifier(raw_change.get("type"), field="drift_resource_type")
        if allowed.get(address) != resource_type:
            if resource_type == "aws_budgets_budget" or resource_type.startswith("aws_budgets_"):
                raise PlanEvidenceError("plan_budget_resource_forbidden")
            raise PlanEvidenceError("plan_drift_resource_not_allowlisted")
        provider = _safe_identifier(raw_change.get("provider_name"), field="drift_provider")
        expected_provider = (
            TERRAFORM_PROVIDER if resource_type == "terraform_data" else AWS_PROVIDER
        )
        if provider != expected_provider:
            raise PlanEvidenceError("plan_drift_provider_mismatch")
        if _instance_base(address) not in REQUIRED_TAGGED_BASES:
            raise PlanEvidenceError("plan_drift_ownership_unverifiable")
        drift_change = raw_change.get("change")
        if not isinstance(drift_change, dict):
            raise PlanEvidenceError("plan_drift_change_invalid")
        actions = _safe_actions(drift_change.get("actions"))
        if actions != ["update"]:
            raise PlanEvidenceError("plan_recovery_drift_action_forbidden")
        desired_resource = changes_by_address.get(address)
        if (
            not isinstance(desired_resource, dict)
            or desired_resource.get("mode") != "managed"
            or desired_resource.get("type") != resource_type
            or desired_resource.get("provider_name") != provider
        ):
            raise PlanEvidenceError("plan_recovery_drift_desired_resource_mismatch")
        desired_change = desired_resource.get("change")
        if not isinstance(desired_change, dict) or _safe_actions(desired_change.get("actions")) != [
            "no-op"
        ]:
            raise PlanEvidenceError("plan_recovery_drift_desired_action_not_noop")
        drift_after = drift_change.get("after")
        desired_after = desired_change.get("after")
        if (
            not isinstance(drift_after, dict)
            or not isinstance(desired_after, dict)
            or drift_after != desired_after
        ):
            raise PlanEvidenceError("plan_recovery_drift_desired_state_mismatch")
        _validate_tags(drift_change, manifest)
        drift.append(
            {
                "address": address,
                "actions": actions,
                "provider": provider,
                "resource_type": resource_type,
            }
        )
    return sorted(drift, key=lambda item: item["address"])


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

    _validate_workflow_identity(
        repository=repository,
        run_id=run_id,
        run_attempt=run_attempt,
        workflow_ref=workflow_ref,
    )
    _validate_plan_status(plan, stage=manifest.stage)
    raw_changes = plan.get("resource_changes", [])
    if not isinstance(raw_changes, list):
        raise PlanEvidenceError("plan_resource_changes_not_array")
    if manifest.stage == "destroy":
        drift_changes = _validate_destroy_drift(plan, manifest)
    elif manifest.stage == "prerequisites":
        drift_changes = _validate_prerequisite_recovery_drift(plan, manifest, raw_changes)
    else:
        drift_changes = []
    changes: list[dict[str, Any]] = []
    changes_by_address: dict[str, dict[str, Any]] = {}
    seen_resource_instances: set[tuple[str, str | None]] = set()
    action_counts: Counter[str] = Counter()
    managed_change_count = 0
    deposed_delete_count = 0
    for raw_change in raw_changes:
        if not isinstance(raw_change, dict):
            raise PlanEvidenceError("plan_resource_change_not_object")
        change = raw_change.get("change")
        if not isinstance(change, dict):
            raise PlanEvidenceError("plan_change_invalid")
        address = _safe_identifier(raw_change.get("address"), field="address")
        base = _instance_base(address)
        mode = raw_change.get("mode")
        if mode not in {"data", "managed"}:
            raise PlanEvidenceError("plan_resource_mode_invalid")
        deposed: str | None = None
        if "deposed" in raw_change:
            candidate = raw_change["deposed"]
            if not isinstance(candidate, str) or DEPOSED_KEY_PATTERN.fullmatch(candidate) is None:
                raise PlanEvidenceError("plan_deposed_key_invalid")
            if manifest.stage != "destroy" or mode != "managed":
                raise PlanEvidenceError("plan_deposed_forbidden")
            deposed = candidate
        resource_identity = (address, deposed)
        if resource_identity in seen_resource_instances:
            raise PlanEvidenceError("plan_resource_address_duplicate")
        seen_resource_instances.add(resource_identity)
        resource_type = _safe_identifier(raw_change.get("type"), field="resource_type")
        allowed = _allowed_resource_addresses(manifest, mode=mode)
        if allowed.get(address) != resource_type:
            if resource_type == "aws_budgets_budget" or resource_type.startswith("aws_budgets_"):
                raise PlanEvidenceError("plan_budget_resource_forbidden")
            raise PlanEvidenceError("plan_resource_not_allowlisted")
        provider = _safe_identifier(raw_change.get("provider_name"), field="provider")
        expected_provider = (
            TERRAFORM_PROVIDER if resource_type == "terraform_data" else AWS_PROVIDER
        )
        if provider != expected_provider:
            raise PlanEvidenceError("plan_resource_provider_mismatch")
        actions = _safe_actions(change.get("actions"))
        _validate_actions(actions, stage=manifest.stage, mode=mode, address=address)
        if mode == "managed":
            managed_change_count += 1
            if deposed is not None:
                deposed_delete_count += 1
        if mode == "managed" and base in REQUIRED_TAGGED_BASES:
            _validate_tags(change, manifest)
        if deposed is None:
            changes_by_address[address] = change
        action_key = "/".join(actions)
        action_counts[action_key] += 1
        changes.append(
            {
                "address": address,
                "actions": actions,
                "provider": provider,
                "resource_type": resource_type,
            }
        )
    output_changes = plan.get("output_changes", {})
    if not isinstance(output_changes, dict):
        raise PlanEvidenceError("plan_output_changes_not_object")
    outputs: list[dict[str, Any]] = []
    seen_outputs: set[str] = set()
    for name, raw_output in sorted(output_changes.items()):
        if name in seen_outputs:
            raise PlanEvidenceError("plan_output_address_duplicate")
        seen_outputs.add(name)
        if name not in ALLOWED_OUTPUTS:
            raise PlanEvidenceError("plan_output_not_allowlisted")
        if not isinstance(raw_output, dict):
            raise PlanEvidenceError("plan_output_change_invalid")
        actions = _safe_actions(raw_output.get("actions"))
        _validate_output_actions(actions, stage=manifest.stage)
        sensitive = raw_output.get("after_sensitive", False)
        if not isinstance(sensitive, bool):
            raise PlanEvidenceError("plan_output_sensitivity_invalid")
        outputs.append(
            {
                "name": _safe_identifier(name, field="output_name"),
                "actions": actions,
                "sensitive": sensitive,
            }
        )
    if manifest.stage == "destroy" and managed_change_count == 0:
        raise PlanEvidenceError("plan_destroy_managed_delete_missing")
    attestations = _validate_stage_contract(changes_by_address, manifest)
    if manifest.stage == "destroy":
        attestations["deposed_managed_deletes_verified"] = True
        attestations["destroy_owned_drift_boundary_verified"] = True
    elif drift_changes:
        attestations["prerequisite_owned_noop_drift_verified"] = True
    masked_account = f"********{manifest.account_id[-4:]}"
    return {
        "schema_version": "modelguard.redacted-terraform-plan.v1",
        "redaction": (
            "all before/after values, configuration, variables, and sensitive payloads omitted"
        ),
        "identity": {
            "account_id_masked": masked_account,
            "activate_services": manifest.activate_services,
            "source_activation_state": manifest.source_activation_state,
            "teardown_authorized": manifest.teardown_authorized,
            "auto_destroy_date": manifest.auto_destroy_date.isoformat(),
            "backend_config_sha256": manifest.backend_config_sha256,
            "deployment_governance_mode": manifest.deployment_governance_mode,
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
            "format_version": _safe_identifier(
                plan.get("format_version"), field="format_version", maximum=30
            ),
            "terraform_version": _safe_identifier(
                plan.get("terraform_version"), field="terraform_version", maximum=80
            ),
        },
        "action_counts": dict(sorted(action_counts.items())),
        "deposed_delete_count": deposed_delete_count,
        "drift_change_count": len(drift_changes),
        "contract_attestations": attestations,
        "drift_changes": drift_changes,
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
        f"- Deployment governance mode: `{identity['deployment_governance_mode']}`",
        f"- Runtime activation: `{str(identity['activate_services']).lower()}`",
        (f"- Pre-destroy runtime source state: `{identity['source_activation_state']}`")
        if identity["stage"] == "destroy"
        else "- Pre-destroy runtime source state: `not-applicable`",
        f"- Teardown authorized: `{str(identity['teardown_authorized']).lower()}`",
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
    if identity["stage"] == "destroy":
        lines.append(f"- Deposed managed deletes: `{summary['deposed_delete_count']}`")
    if summary["drift_change_count"]:
        lines.append(f"- Owned drift changes: `{summary['drift_change_count']}`")
    lines.extend(["", "## Contract attestations", ""])
    attestations = summary["contract_attestations"]
    if attestations:
        lines.extend(
            f"- `{name}`: `{str(value).lower()}`" for name, value in sorted(attestations.items())
        )
    else:
        lines.append("- No contract attestations.")
    lines.extend(["", "## Resource actions", ""])
    changes = summary["resource_changes"]
    if changes:
        lines.extend(f"- `{'/'.join(item['actions'])}` `{item['address']}`" for item in changes)
    else:
        lines.append("- No resource changes.")
    if summary["drift_change_count"]:
        lines.extend(["", "## Owned drift actions", ""])
        drift_changes = summary["drift_changes"]
        if drift_changes:
            lines.extend(
                f"- `{'/'.join(item['actions'])}` `{item['address']}`" for item in drift_changes
            )
        else:
            lines.append("- No owned drift changes.")
    lines.append("")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plan-evidence")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
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
        manifest = load_plan_manifest(args.manifest)
        verify_opaque_plan(args.plan, manifest)
        raw_plan = load_terraform_show_json(sys.stdin)
        summary = summarize_plan(
            raw_plan,
            manifest,
            repository=args.repository,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            workflow_ref=args.workflow_ref,
        )
        write_evidence_file(
            args.output_json,
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
        )
        write_evidence_file(args.output_markdown, render_markdown(summary))
        print(json.dumps({"status": "passed", "resources": len(summary["resource_changes"])}))
        return 0
    except OSError:
        reason = "plan_evidence_io_failed"
    except json.JSONDecodeError:
        reason = "plan_json_invalid"
    except GuardError as error:
        reason = str(error).splitlines()[0][:160]
    except PlanEvidenceError as error:
        reason = str(error).splitlines()[0][:160]
    print(json.dumps({"status": "refused", "reason": reason}), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
