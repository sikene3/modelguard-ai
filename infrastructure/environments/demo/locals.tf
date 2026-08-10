data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  partition   = data.aws_partition.current.partition
  name_prefix = "${var.project_name}-${var.environment}"
  unique_name = "${local.name_prefix}-${var.aws_account_id}-${var.aws_region}"

  common_tags = {
    Project         = var.project_name
    Environment     = var.environment
    Owner           = var.owner_tag
    ManagedBy       = "Terraform"
    Ownership       = "demo"
    AutoDestroyDate = var.auto_destroy_date
  }

  bucket_definitions = {
    models = {
      name                    = "${local.unique_name}-models"
      expiration_days         = 30
      noncurrent_expiration   = 7
      receives_access_logging = true
    }
    predictions = {
      name                    = "${local.unique_name}-predictions"
      expiration_days         = 14
      noncurrent_expiration   = 7
      receives_access_logging = true
    }
    reports = {
      name                    = "${local.unique_name}-reports"
      expiration_days         = 30
      noncurrent_expiration   = 7
      receives_access_logging = true
    }
    audit = {
      name                    = "${local.unique_name}-audit"
      expiration_days         = 30
      noncurrent_expiration   = 7
      receives_access_logging = false
    }
  }
  bucket_arns = {
    for key, bucket in local.bucket_definitions :
    key => "arn:${local.partition}:s3:::${bucket.name}"
  }
  ecr_repository_names = {
    api       = "${var.project_name}/${var.environment}/api"
    dashboard = "${var.project_name}/${var.environment}/dashboard"
    monitor   = "${var.project_name}/${var.environment}/monitor"
  }
  alert_alarm_arns = [
    for name in [
      "alb-api-5xx",
      "alb-api-latency",
      "alb-api-healthy-hosts",
      "alb-dashboard-healthy-hosts",
      "firehose-delivery",
      "scheduler-target-errors",
      "api-event-write-failures",
      "monitor-completion",
      "monitor-input",
      "monitor-rejected",
      "monitor-predictions",
      "monitor-report-freshness",
    ] : "arn:${local.partition}:cloudwatch:${var.aws_region}:${var.aws_account_id}:alarm:${local.name_prefix}-${name}"
  ]

  workload_path = "/${var.project_name}/${var.environment}/"
  expected_permission_boundary_arn = (
    "arn:${local.partition}:iam::${var.aws_account_id}:policy/${var.project_name}/bootstrap/${var.project_name}-workload-boundary"
  )
  placeholder_digest = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  effective_image_refs = {
    api = coalesce(
      var.api_image_ref,
      "${module.data_plane.ecr_repository_urls["api"]}@${local.placeholder_digest}",
    )
    dashboard = coalesce(
      var.dashboard_image_ref,
      "${module.data_plane.ecr_repository_urls["dashboard"]}@${local.placeholder_digest}",
    )
    monitor = coalesce(
      var.monitor_image_ref,
      "${module.data_plane.ecr_repository_urls["monitor"]}@${local.placeholder_digest}",
    )
  }

  runtime_desired_count  = var.activate_services ? 1 : 0
  monitor_schedule_state = var.activate_services ? "ENABLED" : "DISABLED"

  unset_pointer = jsonencode({
    pointer_schema_version = "modelguard.unset.v1"
    model_version          = "UNSET"
    manifest_sha256        = "UNSET"
  })

  expected_bundle_filenames = toset([
    "baseline_profile.json",
    "checksums.sha256",
    "input_schema.json",
    "manifest.json",
    "metrics.json",
    "model.joblib",
    "threshold.json",
  ])
  schedule_period_seconds = {
    "rate(1 hour)"  = 3600
    "rate(2 hours)" = 7200
    "rate(3 hours)" = 10800
    "rate(6 hours)" = 21600
  }

  active_pointer = var.activate_services ? try(jsondecode(data.aws_ssm_parameter.active_current[0].value), {}) : {}
  active_model_version = var.activate_services ? try(
    local.active_pointer.target_identity.model_version,
    "UNSET",
  ) : "0.0.0"
  active_manifest_sha256 = var.activate_services ? try(
    local.active_pointer.target_identity.bundle_manifest_sha256,
    "UNSET",
  ) : "UNSET"
}

resource "terraform_data" "deployment_guard" {
  input = {
    deployment_governance_mode = var.deployment_governance_mode
    deployment_stage           = var.deployment_stage
    environment                = var.environment
    project                    = var.project_name
  }

  lifecycle {
    precondition {
      condition = (
        data.aws_caller_identity.current.account_id == var.aws_account_id &&
        data.aws_region.current.region == var.aws_region &&
        var.project_name == "modelguard-ai" &&
        var.environment == "demo" &&
        local.common_tags.Project == "modelguard-ai" &&
        local.common_tags.Environment == "demo" &&
        var.backend_bucket_name == "${var.project_name}-terraform-state-${var.aws_account_id}-${var.aws_region}" &&
        var.backend_state_key == "modelguard-ai/demo/terraform.tfstate"
      )
      error_message = "Refusing a mismatched account, Region, project, environment, backend key, or tag identity."
    }

    precondition {
      condition = length(distinct(concat(
        var.public_subnet_cidrs,
        var.private_subnet_cidrs,
      ))) == 4
      error_message = "Public and private subnet CIDRs must be four distinct networks."
    }

    precondition {
      condition = alltrue([
        for zone in var.availability_zones :
        can(regex("^${var.aws_region}[a-z]$", zone))
      ])
      error_message = "Every availability zone must belong to aws_region."
    }

    precondition {
      condition = try(
        local.schedule_period_seconds[var.monitor_schedule_expression] == var.monitor_heartbeat_period_seconds,
        false,
      )
      error_message = "monitor_heartbeat_period_seconds must exactly match monitor_schedule_expression."
    }

    precondition {
      condition     = var.permission_boundary_arn == local.expected_permission_boundary_arn
      error_message = "Refusing a workload boundary that is not the exact bootstrap-owned policy."
    }

    precondition {
      condition = var.teardown_authorized || try(
        (
          timecmp("${var.auto_destroy_date}T23:59:59Z", plantimestamp()) >= 0 &&
          timecmp("${var.auto_destroy_date}T23:59:59Z", timeadd(plantimestamp(), "336h")) <= 0
        ),
        false
      )
      error_message = "auto_destroy_date must be today through 14 days unless the exact dormant teardown contract is authorized."
    }

    precondition {
      condition = (
        (
          !var.teardown_authorized &&
          var.deployment_stage == "prerequisites" &&
          !var.activate_services &&
          var.expected_model_version == null &&
          var.expected_model_manifest_sha256 == null &&
          length(var.expected_model_object_version_ids) == 0
        ) ||
        (
          !var.teardown_authorized &&
          var.deployment_stage == "activation" &&
          var.activate_services &&
          var.expected_model_version != null &&
          var.expected_model_manifest_sha256 != null
        ) ||
        (
          var.teardown_authorized &&
          var.deployment_stage == "prerequisites" &&
          !var.activate_services &&
          !var.runtime_contract_verified &&
          !var.budget_prerequisite_verified &&
          var.api_image_ref == null &&
          var.dashboard_image_ref == null &&
          var.monitor_image_ref == null &&
          var.expected_model_version == null &&
          var.expected_model_manifest_sha256 == null &&
          length(var.expected_model_object_version_ids) == 0
        )
      )
      error_message = "Prerequisites and activation forbid teardown authorization; teardown requires dormant prerequisite-form runtime inputs."
    }

    precondition {
      condition = try(
        (
          var.api_access_mode == "https_token" &&
          var.acm_certificate_arn != null &&
          startswith(var.acm_certificate_arn, "arn:${local.partition}:acm:${var.aws_region}:${var.aws_account_id}:certificate/") &&
          var.prediction_token_ssm_arn != null &&
          startswith(var.prediction_token_ssm_arn, "arn:${local.partition}:ssm:${var.aws_region}:${var.aws_account_id}:parameter/${var.project_name}/${var.environment}/secrets/")
        ) ||
        (var.api_access_mode == "http_cidr_only" && var.acm_certificate_arn == null && var.prediction_token_ssm_arn == null),
        false,
      )
      error_message = "https_token requires same-account/Region ACM and SSM SecureString ARNs; http_cidr_only forbids token/certificate inputs."
    }

    precondition {
      condition = !var.activate_services ? true : alltrue([
        for component, reference in {
          api       = var.api_image_ref
          dashboard = var.dashboard_image_ref
          monitor   = var.monitor_image_ref
        } :
        try(
          reference != null &&
          startswith(
            reference,
            "${var.aws_account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/${var.project_name}/${var.environment}/${component}@sha256:",
          ) &&
          can(regex("@sha256:[0-9a-f]{64}$", reference)) &&
          !endswith(reference, local.placeholder_digest),
          false,
        )
      ])
      error_message = "Activation requires three exact in-project ECR repository@sha256 image references; tags/placeholders are forbidden."
    }

    precondition {
      condition     = !var.activate_services || var.runtime_contract_verified
      error_message = "Activation requires reviewed image tests proving API model bootstrap, dashboard S3 reads, and one-shot aws-run monitor behavior."
    }

    precondition {
      condition = !var.activate_services ? true : (
        try(local.active_pointer.pointer_schema_version, "") == "modelguard.active-monitor-target.v1" &&
        try(
          toset(keys(local.active_pointer.target_identity)) == toset([
            "event_schema_version",
            "model_version",
            "bundle_manifest_sha256",
            "input_schema_version",
          ]) &&
          toset(keys(local.active_pointer.bundle)) == toset([
            "bucket",
            "key_prefix",
            "object_version_ids",
          ]),
          false,
        ) &&
        try(local.active_pointer.target_identity.event_schema_version, "") == "modelguard.prediction-event.v1" &&
        try(local.active_pointer.target_identity.input_schema_version, "") == "modelguard.input.v1" &&
        can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", local.active_model_version)) &&
        can(regex("^[0-9a-f]{64}$", local.active_manifest_sha256)) &&
        local.active_model_version == var.expected_model_version &&
        local.active_manifest_sha256 == var.expected_model_manifest_sha256 &&
        try(local.active_pointer.bundle.bucket, "") == local.bucket_definitions.models.name &&
        try(local.active_pointer.bundle.key_prefix, "") == "model-bundles/${local.active_model_version}/" &&
        try(
          toset(keys(local.active_pointer.bundle.object_version_ids)) == local.expected_bundle_filenames &&
          tomap(local.active_pointer.bundle.object_version_ids) == var.expected_model_object_version_ids &&
          alltrue([
            for filename in local.expected_bundle_filenames :
            length(local.active_pointer.bundle.object_version_ids[filename]) > 0
          ]),
          false,
        )
      )
      error_message = "Activation requires the live pointer to equal the verified model version, manifest digest, schemas, and all seven S3 VersionIds."
    }
  }
}
