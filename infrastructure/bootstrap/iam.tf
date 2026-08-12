locals {
  partition       = data.aws_partition.current.partition
  github_oidc_arn = "arn:${local.partition}:iam::${var.aws_account_id}:oidc-provider/token.actions.githubusercontent.com"

  github_repository_parts = split("/", var.github_repository)
  github_repository_subject = var.github_oidc_use_immutable_subject ? (
    "repo:${local.github_repository_parts[0]}@${var.github_repository_owner_id}/${local.github_repository_parts[1]}@${var.github_repository_id}"
  ) : "repo:${var.github_repository}"
  github_workflow_ref_prefix = "${var.github_repository}/"

  plan_subject = join(":", [
    local.github_repository_subject,
    "ref",
    var.github_allowed_ref,
    "environment",
    var.github_plan_environment,
    "workflow_ref",
    "${local.github_workflow_ref_prefix}${var.github_plan_workflow_path}@${var.github_allowed_ref}",
  ])
  deploy_subjects = {
    deploy = join(":", [
      local.github_repository_subject,
      "ref",
      var.github_allowed_ref,
      "environment",
      var.github_deploy_environment,
      "workflow_ref",
      "${local.github_workflow_ref_prefix}${var.github_deploy_workflow_path}@${var.github_allowed_ref}",
    ])
    publish = join(":", [
      local.github_repository_subject,
      "ref",
      var.github_allowed_ref,
      "environment",
      var.github_deploy_environment,
      "workflow_ref",
      "${local.github_workflow_ref_prefix}${var.github_publish_workflow_path}@${var.github_allowed_ref}",
    ])
    rollback = join(":", [
      local.github_repository_subject,
      "ref",
      var.github_allowed_ref,
      "environment",
      var.github_deploy_environment,
      "workflow_ref",
      "${local.github_workflow_ref_prefix}${var.github_rollback_workflow_path}@${var.github_allowed_ref}",
    ])
    destroy = join(":", [
      local.github_repository_subject,
      "ref",
      var.github_allowed_ref,
      "environment",
      var.github_destroy_environment,
      "workflow_ref",
      "${local.github_workflow_ref_prefix}${var.github_destroy_workflow_path}@${var.github_allowed_ref}",
    ])
  }

  bootstrap_path          = "/${var.project_name}/bootstrap/"
  workload_path           = "/${var.project_name}/demo/"
  permission_boundary_arn = "arn:${local.partition}:iam::${var.aws_account_id}:policy${local.bootstrap_path}${var.project_name}-workload-boundary"

  demo_prefix = "${var.project_name}-demo-${var.aws_account_id}-${var.aws_region}"
  demo_bucket_arns = {
    models      = "arn:${local.partition}:s3:::${local.demo_prefix}-models"
    predictions = "arn:${local.partition}:s3:::${local.demo_prefix}-predictions"
    reports     = "arn:${local.partition}:s3:::${local.demo_prefix}-reports"
    audit       = "arn:${local.partition}:s3:::${local.demo_prefix}-audit"
  }
  demo_object_arns = [for arn in values(local.demo_bucket_arns) : "${arn}/*"]
  ecr_repository_arns = [
    for component in ["api", "dashboard", "monitor"] :
    "arn:${local.partition}:ecr:${var.aws_region}:${var.aws_account_id}:repository/${var.project_name}/demo/${component}"
  ]
  workload_role_names = [
    "ecs-execution",
    "api",
    "dashboard",
    "monitor",
    "firehose",
    "scheduler",
  ]
  workload_role_arns = {
    for role in local.workload_role_names : role =>
    "arn:${local.partition}:iam::${var.aws_account_id}:role${local.workload_path}${var.project_name}-demo-${role}"
  }
  workload_role_resources = values(local.workload_role_arns)
  log_group_arns = [
    for component in ["api", "dashboard", "monitor", "firehose"] :
    "arn:${local.partition}:logs:${var.aws_region}:${var.aws_account_id}:log-group:/${var.project_name}/demo/${component}"
  ]
  log_stream_arns      = [for arn in local.log_group_arns : "${arn}:log-stream:*"]
  firehose_arn         = "arn:${local.partition}:firehose:${var.aws_region}:${var.aws_account_id}:deliverystream/${var.project_name}-demo-predictions"
  sns_topic_arn        = "arn:${local.partition}:sns:${var.aws_region}:${var.aws_account_id}:${var.project_name}-demo-alerts"
  aws_managed_key_arns = "arn:${local.partition}:kms:${var.aws_region}:${var.aws_account_id}:key/*"
  cluster_arn          = "arn:${local.partition}:ecs:${var.aws_region}:${var.aws_account_id}:cluster/${var.project_name}-demo"
  ecs_service_arns = [
    for component in ["api", "dashboard"] :
    "arn:${local.partition}:ecs:${var.aws_region}:${var.aws_account_id}:service/${var.project_name}-demo/${var.project_name}-demo-${component}"
  ]
  task_definition_arns = [
    for component in ["api", "dashboard", "monitor"] :
    "arn:${local.partition}:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${var.project_name}-demo-${component}:*"
  ]
  monitor_task_arn = local.task_definition_arns[2]
  alb_resource_arns = [
    "arn:${local.partition}:elasticloadbalancing:${var.aws_region}:${var.aws_account_id}:loadbalancer/app/${var.project_name}-demo/*",
    "arn:${local.partition}:elasticloadbalancing:${var.aws_region}:${var.aws_account_id}:listener/app/${var.project_name}-demo/*/*",
    "arn:${local.partition}:elasticloadbalancing:${var.aws_region}:${var.aws_account_id}:listener-rule/app/${var.project_name}-demo/*/*/*",
    "arn:${local.partition}:elasticloadbalancing:${var.aws_region}:${var.aws_account_id}:targetgroup/${var.project_name}-demo-api/*",
    "arn:${local.partition}:elasticloadbalancing:${var.aws_region}:${var.aws_account_id}:targetgroup/${var.project_name}-demo-dashboard/*",
  ]
  schedule_group_arn = "arn:${local.partition}:scheduler:${var.aws_region}:${var.aws_account_id}:schedule-group/${var.project_name}-demo-monitor"
  schedule_arn       = "arn:${local.partition}:scheduler:${var.aws_region}:${var.aws_account_id}:schedule/${var.project_name}-demo-monitor/${var.project_name}-demo-monitor"
  alarm_arn          = "arn:${local.partition}:cloudwatch:${var.aws_region}:${var.aws_account_id}:alarm:${var.project_name}-demo-*"
  budget_arn         = "arn:${local.partition}:budgets::${var.aws_account_id}:budget/${var.project_name}-demo-monthly"
  billing_view_arns  = "arn:${local.partition}:billing::${var.aws_account_id}:billingview/*"
  certificate_arns   = "arn:${local.partition}:acm:${var.aws_region}:${var.aws_account_id}:certificate/*"
  parameter_root_arn = "arn:${local.partition}:ssm:${var.aws_region}:${var.aws_account_id}:parameter/${var.project_name}/demo"

  ec2_network_resource_arns = {
    elastic_ip          = "arn:${local.partition}:ec2:${var.aws_region}:${var.aws_account_id}:elastic-ip/*"
    internet_gateway    = "arn:${local.partition}:ec2:${var.aws_region}:${var.aws_account_id}:internet-gateway/*"
    nat_gateway         = "arn:${local.partition}:ec2:${var.aws_region}:${var.aws_account_id}:natgateway/*"
    route_table         = "arn:${local.partition}:ec2:${var.aws_region}:${var.aws_account_id}:route-table/*"
    security_group      = "arn:${local.partition}:ec2:${var.aws_region}:${var.aws_account_id}:security-group/*"
    security_group_rule = "arn:${local.partition}:ec2:${var.aws_region}:${var.aws_account_id}:security-group-rule/*"
    subnet              = "arn:${local.partition}:ec2:${var.aws_region}:${var.aws_account_id}:subnet/*"
    vpc                 = "arn:${local.partition}:ec2:${var.aws_region}:${var.aws_account_id}:vpc/*"
    vpc_endpoint        = "arn:${local.partition}:ec2:${var.aws_region}:${var.aws_account_id}:vpc-endpoint/*"
  }
  ec2_network_resource_arn_list = values(local.ec2_network_resource_arns)
  ec2_network_create_actions = [
    "ec2:AllocateAddress",
    "ec2:CreateInternetGateway",
    "ec2:CreateNatGateway",
    "ec2:CreateRouteTable",
    "ec2:CreateSecurityGroup",
    "ec2:CreateSubnet",
    "ec2:CreateVpc",
    "ec2:CreateVpcEndpoint",
  ]
  ec2_network_association_actions = [
    "ec2:AssociateRouteTable",
    "ec2:AttachInternetGateway",
    "ec2:DetachInternetGateway",
    "ec2:DisassociateRouteTable",
  ]
  ec2_network_mutation_actions = [
    "ec2:AuthorizeSecurityGroupEgress",
    "ec2:AuthorizeSecurityGroupIngress",
    "ec2:CreateRoute",
    "ec2:ModifySubnetAttribute",
    "ec2:ModifyVpcAttribute",
    "ec2:ModifyVpcEndpoint",
    "ec2:RevokeSecurityGroupEgress",
    "ec2:RevokeSecurityGroupIngress",
  ]
  ec2_network_delete_actions = [
    "ec2:DeleteInternetGateway",
    "ec2:DeleteNatGateway",
    "ec2:DeleteRoute",
    "ec2:DeleteRouteTable",
    "ec2:DeleteSecurityGroup",
    "ec2:DeleteSubnet",
    "ec2:DeleteTags",
    "ec2:DeleteVpc",
    "ec2:DeleteVpcEndpoints",
    "ec2:ReleaseAddress",
  ]
  ec2_network_lifecycle_actions = concat(
    local.ec2_network_association_actions,
    local.ec2_network_mutation_actions,
    local.ec2_network_delete_actions,
  )
  ec2_network_boundary_tagged_actions = concat(
    local.ec2_network_association_actions,
    [
      "ec2:CreateRoute",
      "ec2:DeleteInternetGateway",
      "ec2:DeleteNatGateway",
      "ec2:DeleteRoute",
      "ec2:DeleteRouteTable",
      "ec2:DeleteSecurityGroup",
      "ec2:DeleteSubnet",
      "ec2:DeleteTags",
      "ec2:DeleteVpc",
      "ec2:DeleteVpcEndpoints",
      "ec2:ModifySubnetAttribute",
      "ec2:ModifyVpcAttribute",
      "ec2:ModifyVpcEndpoint",
      "ec2:ReleaseAddress",
      "ec2:RevokeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress",
    ],
  )
  ec2_network_allowed_tag_keys = [
    "AutoDestroyDate",
    "Environment",
    "ManagedBy",
    "Name",
    "Owner",
    "Ownership",
    "Project",
    "Tier",
  ]
}

data "aws_iam_policy_document" "workload_boundary" {
  statement {
    sid    = "EcrAuthorization"
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "PullExactDemoRepositories"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = local.ecr_repository_arns
  }

  statement {
    sid    = "WriteExactLogGroups"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = local.log_stream_arns
  }

  statement {
    sid    = "ReadDemoBucketMetadata"
    effect = "Allow"
    actions = [
      "s3:GetBucketLocation",
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
    ]
    resources = values(local.demo_bucket_arns)
  }

  statement {
    sid    = "UseDemoObjects"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]
    resources = [for arn in values(local.demo_bucket_arns) : "${arn}/*"]
  }

  statement {
    sid    = "WritePredictionFirehose"
    effect = "Allow"
    actions = [
      "firehose:PutRecord",
      "firehose:PutRecordBatch",
    ]
    resources = [local.firehose_arn]
  }

  statement {
    sid    = "ReadModelPointersAndTokenReference"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
    ]
    resources = ["${local.parameter_root_arn}/*"]
  }

  statement {
    sid       = "PublishDriftAlert"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [local.sns_topic_arn]
  }

  # The AWS-managed SSM key ID is service-created, so the account/Region pattern is constrained by
  # its exact alias. SNS uses the exact retained bootstrap key in the next statement.
  statement {
    sid    = "UseApprovedAwsManagedSsmKey"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [local.aws_managed_key_arns]

    condition {
      test     = "ForAnyValue:StringEquals"
      variable = "kms:ResourceAliases"
      values = [
        "alias/aws/ssm",
      ]
    }
  }

  statement {
    sid    = "UseRetainedKeyForExactAlertTopic"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [aws_kms_key.state.arn]

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:sns:topicArn"
      values   = [local.sns_topic_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["sns.${var.aws_region}.amazonaws.com"]
    }
  }

  statement {
    sid       = "RunExactMonitorTask"
    effect    = "Allow"
    actions   = ["ecs:RunTask"]
    resources = [local.monitor_task_arn]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [local.cluster_arn]
    }
  }

  statement {
    sid    = "PassMonitorRolesToEcsOnly"
    effect = "Allow"
    actions = [
      "iam:PassRole",
    ]
    resources = [
      local.workload_role_arns["ecs-execution"],
      local.workload_role_arns["monitor"],
    ]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_policy" "workload_boundary" {
  name        = "${var.project_name}-workload-boundary"
  path        = local.bootstrap_path
  description = "Mandatory maximum permissions for ModelGuard demo workload roles"
  policy      = data.aws_iam_policy_document.workload_boundary.json

  tags = merge(local.common_tags, { Name = "${var.project_name}-workload-boundary" })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]

  tags = merge(local.common_tags, { Name = "${var.project_name}-github" })

  lifecycle {
    prevent_destroy = true
  }
}

data "aws_iam_policy_document" "github_plan_trust" {
  statement {
    sid     = "ExactCustomizedPlanSubject"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [local.plan_subject]
    }
  }
}

data "aws_iam_policy_document" "github_deploy_trust" {
  statement {
    sid     = "ExactCustomizedDeploySubjects"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = values(local.deploy_subjects)
    }
  }
}

resource "aws_iam_role" "ci_plan" {
  name                 = "${var.project_name}-ci-plan"
  path                 = local.bootstrap_path
  assume_role_policy   = data.aws_iam_policy_document.github_plan_trust.json
  max_session_duration = 3600

  tags = merge(local.common_tags, { Name = "${var.project_name}-ci-plan" })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role" "ci_deploy" {
  name                 = "${var.project_name}-ci-deploy"
  path                 = local.bootstrap_path
  assume_role_policy   = data.aws_iam_policy_document.github_deploy_trust.json
  max_session_duration = 3600
  permissions_boundary = aws_iam_policy.ci_deploy_boundary.arn

  tags = merge(local.common_tags, { Name = "${var.project_name}-ci-deploy" })

  lifecycle {
    prevent_destroy = true
  }
}

data "aws_iam_policy_document" "remote_state_plan" {
  statement {
    sid       = "ListExactStateAndLock"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.state.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "env:/",
        var.state_backend_key,
        "${var.state_backend_key}.tflock",
      ]
    }
  }

  statement {
    sid    = "ReadStateAndManageLock"
    effect = "Allow"
    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.state.arn}/${var.state_backend_key}.tflock",
    ]
  }

  statement {
    sid       = "ReadState"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.state.arn}/${var.state_backend_key}"]
  }

  statement {
    sid    = "UseStateKmsKey"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:Encrypt",
      "kms:GenerateDataKey",
    ]
    resources = [aws_kms_key.state.arn]
  }
}

data "aws_iam_policy_document" "remote_state_deploy" {
  source_policy_documents = [data.aws_iam_policy_document.remote_state_plan.json]

  statement {
    sid    = "WriteExactState"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.state.arn}/${var.state_backend_key}"]
  }

  statement {
    sid       = "ListExactConfidentialPlanTransfers"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.state.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["reviewed-plans/*"]
    }
  }

  statement {
    sid    = "ManageExactConfidentialPlanTransfers"
    effect = "Allow"
    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.state.arn}/reviewed-plans/*"]
  }

  statement {
    sid       = "ListExactPhase10Evidence"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.state.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["phase-10-evidence/teardown/*"]
    }
  }

  statement {
    sid    = "WriteAndVerifyExactPhase10Evidence"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.state.arn}/phase-10-evidence/teardown/*"]
  }
}

data "aws_iam_policy_document" "ci_plan_read" {
  statement {
    sid    = "GlobalReadOnlyDiscovery"
    effect = "Allow"
    actions = [
      "cloudwatch:DescribeAlarms",
      "ec2:DescribeAddresses",
      "ec2:DescribeAvailabilityZones",
      "ec2:DescribeInternetGateways",
      "ec2:DescribeNatGateways",
      "ec2:DescribeNetworkAcls",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeRouteTables",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSubnets",
      "ec2:DescribeTags",
      "ec2:DescribeVpcAttribute",
      "ec2:DescribeVpcEndpoints",
      "ec2:DescribeVpcs",
      "ecr:DescribeRepositories",
      "ecs:DescribeTaskDefinition",
      "ecs:DescribeTasks",
      "ecs:ListClusters",
      "ecs:ListServices",
      "ecs:ListTaskDefinitions",
      "ecs:ListTasks",
      "elasticloadbalancing:DescribeListenerAttributes",
      "elasticloadbalancing:DescribeListeners",
      "elasticloadbalancing:DescribeLoadBalancerAttributes",
      "elasticloadbalancing:DescribeLoadBalancers",
      "elasticloadbalancing:DescribeRules",
      "elasticloadbalancing:DescribeTags",
      "elasticloadbalancing:DescribeTargetGroupAttributes",
      "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:DescribeTargetHealth",
      "firehose:ListDeliveryStreams",
      "iam:ListRoles",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "s3:ListAllMyBuckets",
      "scheduler:ListScheduleGroups",
      "scheduler:ListSchedules",
      "sns:GetSubscriptionAttributes",
      "sns:ListTopics",
      "ssm:DescribeParameters",
      "sts:GetCallerIdentity",
      "tag:GetResources",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ReadExternalCertificateMetadata"
    effect = "Allow"
    actions = [
      "acm:DescribeCertificate",
      "acm:ListTagsForCertificate",
    ]
    resources = [local.certificate_arns]
  }

  statement {
    sid    = "ReadExactBudget"
    effect = "Allow"
    actions = [
      "budgets:ListTagsForResource",
      "budgets:ViewBudget",
    ]
    resources = [local.budget_arn]
  }

  statement {
    sid       = "ReadBillingViewForBudget"
    effect    = "Allow"
    actions   = ["billing:GetBillingViewData"]
    resources = [local.billing_view_arns]
  }

  statement {
    sid       = "UseLegacyGlobalBillingViewPermission"
    effect    = "Allow"
    actions   = ["aws-portal:ViewBilling"]
    resources = ["*"]
  }

  statement {
    sid    = "ReadExactAlarms"
    effect = "Allow"
    actions = [
      "cloudwatch:ListTagsForResource",
    ]
    resources = [local.alarm_arn]
  }

  statement {
    sid    = "ReadExactRepositories"
    effect = "Allow"
    actions = [
      "ecr:GetLifecyclePolicy",
      "ecr:GetRepositoryPolicy",
      "ecr:ListImages",
      "ecr:ListTagsForResource",
    ]
    resources = local.ecr_repository_arns
  }

  statement {
    sid    = "ReadExactEcsResources"
    effect = "Allow"
    actions = [
      "ecs:DescribeClusters",
      "ecs:DescribeServices",
      "ecs:ListTagsForResource",
    ]
    resources = concat(
      [local.cluster_arn],
      local.ecs_service_arns,
      local.task_definition_arns,
    )
  }

  statement {
    sid    = "ReadExactFirehose"
    effect = "Allow"
    actions = [
      "firehose:DescribeDeliveryStream",
      "firehose:ListTagsForDeliveryStream",
    ]
    resources = [local.firehose_arn]
  }

  statement {
    sid    = "ReadExactWorkloadRoles"
    effect = "Allow"
    actions = [
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
    ]
    resources = local.workload_role_resources
  }

  statement {
    sid    = "ReadExactLogGroups"
    effect = "Allow"
    actions = [
      "logs:ListTagsForResource",
    ]
    resources = local.log_group_arns
  }

  statement {
    sid    = "ReadExactSchedules"
    effect = "Allow"
    actions = [
      "scheduler:GetSchedule",
      "scheduler:GetScheduleGroup",
      "scheduler:ListTagsForResource",
    ]
    resources = [
      local.schedule_group_arn,
      local.schedule_arn,
    ]
  }

  statement {
    sid    = "ReadExactDemoBuckets"
    effect = "Allow"
    actions = [
      "s3:GetAccelerateConfiguration",
      "s3:GetBucketAcl",
      "s3:GetBucketCors",
      "s3:GetBucketLocation",
      "s3:GetBucketLogging",
      "s3:GetBucketObjectLockConfiguration",
      "s3:GetBucketOwnershipControls",
      "s3:GetBucketPolicy",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketRequestPayment",
      "s3:GetBucketTagging",
      "s3:GetBucketVersioning",
      "s3:GetEncryptionConfiguration",
      "s3:GetLifecycleConfiguration",
      "s3:GetReplicationConfiguration",
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
    ]
    resources = values(local.demo_bucket_arns)
  }

  statement {
    sid    = "ReadExactAlertTopic"
    effect = "Allow"
    actions = [
      "sns:GetTopicAttributes",
      "sns:ListSubscriptionsByTopic",
      "sns:ListTagsForResource",
    ]
    resources = [local.sns_topic_arn]
  }

  statement {
    sid    = "ReadExactParameters"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParametersByPath",
      "ssm:ListTagsForResource",
    ]
    resources = ["${local.parameter_root_arn}/*"]
  }
}

data "aws_iam_policy_document" "ci_deploy_compute" {
  # checkov:skip=CKV_AWS_111:ECS CreateCluster has no resource-level authorization; exact request tags constrain creation, while every addressable ECS/ALB operation uses exact demo ARNs. [owner=modelguard-maintainers; expires=2026-10-31]
  # checkov:skip=CKV_AWS_356:ECS CreateCluster requires Resource="*" and is constrained by exact request tags; all other compute resources are exact demo ARNs. [owner=modelguard-maintainers; expires=2026-10-31]

  statement {
    sid       = "CreateOnlyTaggedDemoCluster"
    effect    = "Allow"
    actions   = ["ecs:CreateCluster"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = ["demo"]
    }
  }

  statement {
    sid    = "ManageExactDemoEcsResources"
    effect = "Allow"
    actions = [
      "ecs:CreateService",
      "ecs:DeleteCluster",
      "ecs:DeleteService",
      "ecs:DeleteTaskDefinitions",
      "ecs:DeregisterTaskDefinition",
      "ecs:RegisterTaskDefinition",
      "ecs:TagResource",
      "ecs:UntagResource",
      "ecs:UpdateClusterSettings",
      "ecs:UpdateService",
    ]
    resources = concat(
      [local.cluster_arn],
      local.ecs_service_arns,
      local.task_definition_arns,
    )
  }

  statement {
    sid    = "ManageExactDemoLoadBalancerResources"
    effect = "Allow"
    actions = [
      "elasticloadbalancing:AddTags",
      "elasticloadbalancing:CreateListener",
      "elasticloadbalancing:CreateLoadBalancer",
      "elasticloadbalancing:CreateRule",
      "elasticloadbalancing:CreateTargetGroup",
      "elasticloadbalancing:DeleteListener",
      "elasticloadbalancing:DeleteLoadBalancer",
      "elasticloadbalancing:DeleteRule",
      "elasticloadbalancing:DeleteTargetGroup",
      "elasticloadbalancing:ModifyListener",
      "elasticloadbalancing:ModifyLoadBalancerAttributes",
      "elasticloadbalancing:ModifyRule",
      "elasticloadbalancing:ModifyTargetGroup",
      "elasticloadbalancing:ModifyTargetGroupAttributes",
      "elasticloadbalancing:RemoveTags",
      "elasticloadbalancing:SetSecurityGroups",
      "elasticloadbalancing:SetSubnets",
    ]
    resources = local.alb_resource_arns
  }
}

data "aws_iam_policy_document" "ci_deploy_network_create" {
  statement {
    sid       = "CreateTaggedDemoVpc"
    effect    = "Allow"
    actions   = ["ec2:CreateVpc"]
    resources = [local.ec2_network_resource_arns.vpc]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = ["demo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/ManagedBy"
      values   = ["Terraform"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Ownership"
      values   = ["demo"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = local.ec2_network_allowed_tag_keys
    }
  }

  statement {
    sid    = "CreateTaggedDemoVpcChildren"
    effect = "Allow"
    actions = [
      "ec2:CreateRouteTable",
      "ec2:CreateSecurityGroup",
      "ec2:CreateSubnet",
    ]
    resources = [
      local.ec2_network_resource_arns.route_table,
      local.ec2_network_resource_arns.security_group,
      local.ec2_network_resource_arns.subnet,
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = ["demo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/ManagedBy"
      values   = ["Terraform"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Ownership"
      values   = ["demo"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = local.ec2_network_allowed_tag_keys
    }
  }

  statement {
    sid    = "CreateTaggedDemoInternetAndAddressResources"
    effect = "Allow"
    actions = [
      "ec2:AllocateAddress",
      "ec2:CreateInternetGateway",
    ]
    resources = [
      local.ec2_network_resource_arns.elastic_ip,
      local.ec2_network_resource_arns.internet_gateway,
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = ["demo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/ManagedBy"
      values   = ["Terraform"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Ownership"
      values   = ["demo"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = local.ec2_network_allowed_tag_keys
    }
  }

  # Child creation authorizes the new request-tagged object above and the already-tagged VPC here.
  statement {
    sid    = "UseTaggedDemoVpcForChildCreation"
    effect = "Allow"
    actions = [
      "ec2:CreateRouteTable",
      "ec2:CreateSecurityGroup",
      "ec2:CreateSubnet",
    ]
    resources = [local.ec2_network_resource_arns.vpc]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = ["demo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/ManagedBy"
      values   = ["Terraform"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Ownership"
      values   = ["demo"]
    }
  }

  statement {
    sid       = "TagDemoResourcesOnlyAtCreation"
    effect    = "Allow"
    actions   = ["ec2:CreateTags"]
    resources = local.ec2_network_resource_arn_list

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }

    condition {
      test     = "StringEquals"
      variable = "ec2:CreateAction"
      values = [
        "AllocateAddress",
        "AuthorizeSecurityGroupEgress",
        "AuthorizeSecurityGroupIngress",
        "CreateInternetGateway",
        "CreateNatGateway",
        "CreateRouteTable",
        "CreateSecurityGroup",
        "CreateSubnet",
        "CreateVpc",
        "CreateVpcEndpoint",
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = ["demo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/ManagedBy"
      values   = ["Terraform"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Ownership"
      values   = ["demo"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = local.ec2_network_allowed_tag_keys
    }
  }

  # A VPC's generated default security group has no caller-selected ID or tags. This one narrowly
  # scoped bootstrap exception can only attach the complete required demo tag set and exact name;
  # the lifecycle policy below can subsequently revoke its default rules but cannot add rules.
  statement {
    sid       = "TagGuardedDefaultSecurityGroup"
    effect    = "Allow"
    actions   = ["ec2:CreateTags"]
    resources = [local.ec2_network_resource_arns.security_group]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = ["demo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/ManagedBy"
      values   = ["Terraform"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Ownership"
      values   = ["demo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Name"
      values   = ["${var.project_name}-demo-default-deny"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = local.ec2_network_allowed_tag_keys
    }
  }
}

data "aws_iam_policy_document" "ci_deploy_network_dependencies" {
  statement {
    sid       = "CreateTaggedDemoNatGateway"
    effect    = "Allow"
    actions   = ["ec2:CreateNatGateway"]
    resources = [local.ec2_network_resource_arns.nat_gateway]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = ["demo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/ManagedBy"
      values   = ["Terraform"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Ownership"
      values   = ["demo"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = local.ec2_network_allowed_tag_keys
    }
  }

  statement {
    sid     = "UseTaggedDemoParentsForNatGateway"
    effect  = "Allow"
    actions = ["ec2:CreateNatGateway"]
    resources = [
      local.ec2_network_resource_arns.elastic_ip,
      local.ec2_network_resource_arns.subnet,
      local.ec2_network_resource_arns.vpc,
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = ["demo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/ManagedBy"
      values   = ["Terraform"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Ownership"
      values   = ["demo"]
    }
  }

  statement {
    sid       = "CreateTaggedDemoVpcEndpoint"
    effect    = "Allow"
    actions   = ["ec2:CreateVpcEndpoint"]
    resources = [local.ec2_network_resource_arns.vpc_endpoint]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = ["demo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/ManagedBy"
      values   = ["Terraform"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Ownership"
      values   = ["demo"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = local.ec2_network_allowed_tag_keys
    }
  }

  statement {
    sid     = "UseTaggedDemoParentsForVpcEndpoint"
    effect  = "Allow"
    actions = ["ec2:CreateVpcEndpoint"]
    resources = [
      local.ec2_network_resource_arns.route_table,
      local.ec2_network_resource_arns.security_group,
      local.ec2_network_resource_arns.subnet,
      local.ec2_network_resource_arns.vpc,
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = ["demo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/ManagedBy"
      values   = ["Terraform"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Ownership"
      values   = ["demo"]
    }
  }
}

data "aws_iam_policy_document" "ci_deploy_network_lifecycle" {
  statement {
    sid       = "CreateRulesOnlyOnTaggedDemoSecurityGroups"
    effect    = "Allow"
    actions   = ["ec2:AuthorizeSecurityGroupEgress", "ec2:AuthorizeSecurityGroupIngress"]
    resources = [local.ec2_network_resource_arns.security_group_rule]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = ["demo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/ManagedBy"
      values   = ["Terraform"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Ownership"
      values   = ["demo"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = local.ec2_network_allowed_tag_keys
    }
  }

  statement {
    sid       = "MutateTaggedDemoNetworkResources"
    effect    = "Allow"
    actions   = local.ec2_network_mutation_actions
    resources = local.ec2_network_resource_arn_list

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = ["demo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/ManagedBy"
      values   = ["Terraform"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Ownership"
      values   = ["demo"]
    }
  }

  statement {
    sid       = "AssociateTaggedDemoNetworkResources"
    effect    = "Allow"
    actions   = local.ec2_network_association_actions
    resources = local.ec2_network_resource_arn_list

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = ["demo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/ManagedBy"
      values   = ["Terraform"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Ownership"
      values   = ["demo"]
    }
  }

  statement {
    sid       = "DeleteTaggedDemoNetworkResources"
    effect    = "Allow"
    actions   = local.ec2_network_delete_actions
    resources = local.ec2_network_resource_arn_list

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = ["demo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/ManagedBy"
      values   = ["Terraform"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Ownership"
      values   = ["demo"]
    }
  }
}

data "aws_iam_policy_document" "ci_deploy_boundary" {
  # Checkov evaluates this maximum-permissions boundary as if it were an identity policy. A
  # boundary never grants permissions: every request must still be allowed by the separately
  # scanned least-privilege identity policies. These exact suppressions cover only that semantic
  # mismatch; the EC2 Allow below is independently account/Region/resource constrained.
  # checkov:skip=CKV_AWS_107:The non-EC2 NotAction boundary grant cannot expose credentials without a separate identity-policy Allow; existing identity policies remain the granting boundary. [owner=modelguard-maintainers; expires=2026-10-31]
  # checkov:skip=CKV_AWS_108:The non-EC2 NotAction boundary grant cannot exfiltrate data without a separate identity-policy Allow; existing identity policies remain the granting boundary. [owner=modelguard-maintainers; expires=2026-10-31]
  # checkov:skip=CKV_AWS_109:The non-EC2 NotAction boundary grant cannot expose resources without a separate identity-policy Allow; existing identity policies remain the granting boundary. [owner=modelguard-maintainers; expires=2026-10-31]
  # checkov:skip=CKV_AWS_110:The non-EC2 NotAction boundary grant cannot escalate privileges without a separate identity-policy Allow; existing identity policies remain the granting boundary. [owner=modelguard-maintainers; expires=2026-10-31]
  # checkov:skip=CKV_AWS_111:The only EC2 boundary Allow has exact regional ARN patterns and RequestedRegion; the non-EC2 NotAction statement preserves separately constrained identity policies and grants nothing itself. [owner=modelguard-maintainers; expires=2026-10-31]
  # checkov:skip=CKV_AWS_356:The only wildcard Resource belongs to a non-EC2 maximum-permissions boundary statement that grants nothing; restrictable identity-policy actions retain exact resources. [owner=modelguard-maintainers; expires=2026-10-31]

  statement {
    sid         = "PreserveNonEc2LeastPrivilegeIdentityPolicies"
    effect      = "Allow"
    not_actions = ["ec2:*"]
    resources   = ["*"]
  }

  statement {
    sid    = "AllowOnlyGuardedEc2NetworkCandidates"
    effect = "Allow"
    actions = concat(
      local.ec2_network_create_actions,
      local.ec2_network_lifecycle_actions,
      ["ec2:CreateTags"],
    )
    resources = local.ec2_network_resource_arn_list

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }
  }

  statement {
    sid    = "DenyDemoNetworkOutsideApprovedRegion"
    effect = "Deny"
    actions = concat(
      local.ec2_network_create_actions,
      local.ec2_network_lifecycle_actions,
      ["ec2:CreateTags"],
    )
    resources = ["*"]

    condition {
      test     = "StringNotEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }
  }

  statement {
    sid       = "DenyForeignProjectNetworkLifecycle"
    effect    = "Deny"
    actions   = local.ec2_network_boundary_tagged_actions
    resources = local.ec2_network_resource_arn_list

    condition {
      test     = "StringNotEqualsIfExists"
      variable = "aws:ResourceTag/Project"
      values   = [var.project_name]
    }
  }

  statement {
    sid       = "DenyForeignEnvironmentNetworkLifecycle"
    effect    = "Deny"
    actions   = local.ec2_network_boundary_tagged_actions
    resources = local.ec2_network_resource_arn_list

    condition {
      test     = "StringNotEqualsIfExists"
      variable = "aws:ResourceTag/Environment"
      values   = ["demo"]
    }
  }
}

data "aws_iam_policy_document" "ci_deploy_data" {
  statement {
    sid       = "AuthorizeEcrForExactRepositoryOperations"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "ManageExactDemoRepositories"
    effect = "Allow"
    actions = [
      "ecr:CreateRepository",
      "ecr:DeleteLifecyclePolicy",
      "ecr:DeleteRepository",
      "ecr:PutLifecyclePolicy",
      "ecr:PutImageScanningConfiguration",
      "ecr:PutImageTagMutability",
      "ecr:TagResource",
      "ecr:UntagResource",
    ]
    resources = local.ecr_repository_arns
  }

  statement {
    sid    = "PushAndVerifyExactDemoImages"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:ListImages",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = local.ecr_repository_arns
  }

  statement {
    sid    = "ManageExactPredictionDeliveryStream"
    effect = "Allow"
    actions = [
      "firehose:CreateDeliveryStream",
      "firehose:DeleteDeliveryStream",
      "firehose:StartDeliveryStreamEncryption",
      "firehose:StopDeliveryStreamEncryption",
      "firehose:TagDeliveryStream",
      "firehose:UntagDeliveryStream",
      "firehose:UpdateDestination",
    ]
    resources = [local.firehose_arn]
  }

  statement {
    sid    = "ManageExactDemoBuckets"
    effect = "Allow"
    actions = [
      "s3:CreateBucket",
      "s3:DeleteBucket",
      "s3:DeleteBucketPolicy",
      "s3:ListBucketMultipartUploads",
      "s3:ListBucketVersions",
      "s3:PutBucketLogging",
      "s3:PutBucketOwnershipControls",
      "s3:PutBucketPolicy",
      "s3:PutBucketPublicAccessBlock",
      "s3:PutBucketTagging",
      "s3:PutBucketVersioning",
      "s3:PutEncryptionConfiguration",
      "s3:PutLifecycleConfiguration",
    ]
    resources = values(local.demo_bucket_arns)
  }

  statement {
    sid    = "PublishVerifyAndDeleteExactDemoObjects"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]
    resources = local.demo_object_arns
  }

  statement {
    sid    = "ManageExactModelPointers"
    effect = "Allow"
    actions = [
      "ssm:AddTagsToResource",
      "ssm:DeleteParameter",
      "ssm:PutParameter",
      "ssm:RemoveTagsFromResource",
    ]
    resources = ["${local.parameter_root_arn}/models/*"]
  }
}

data "aws_iam_policy_document" "ci_deploy_operations" {
  statement {
    sid    = "ManageExactDemoAlarms"
    effect = "Allow"
    actions = [
      "cloudwatch:DeleteAlarms",
      "cloudwatch:PutMetricAlarm",
      "cloudwatch:TagResource",
      "cloudwatch:UntagResource",
    ]
    resources = [local.alarm_arn]
  }

  statement {
    sid    = "ManageExactDemoLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:DeleteLogGroup",
      "logs:DeleteLogStream",
      "logs:DeleteRetentionPolicy",
      "logs:PutRetentionPolicy",
      "logs:TagResource",
      "logs:UntagResource",
    ]
    resources = concat(local.log_group_arns, local.log_stream_arns)
  }

  statement {
    sid    = "ManageExactMonitorSchedule"
    effect = "Allow"
    actions = [
      "scheduler:CreateSchedule",
      "scheduler:CreateScheduleGroup",
      "scheduler:DeleteSchedule",
      "scheduler:DeleteScheduleGroup",
      "scheduler:TagResource",
      "scheduler:UntagResource",
      "scheduler:UpdateSchedule",
    ]
    resources = [
      local.schedule_group_arn,
      local.schedule_arn,
    ]
  }

  statement {
    sid    = "ManageExactAlertTopic"
    effect = "Allow"
    actions = [
      "sns:CreateTopic",
      "sns:DeleteTopic",
      "sns:SetTopicAttributes",
      "sns:TagResource",
      "sns:UntagResource",
    ]
    resources = [local.sns_topic_arn]
  }

  statement {
    sid       = "ReadRetainedNotificationKeyMetadata"
    effect    = "Allow"
    actions   = ["kms:DescribeKey"]
    resources = [aws_kms_key.state.arn]
  }

}

data "aws_iam_policy_document" "ci_deploy_iam" {
  statement {
    sid       = "CreateOnlyBoundaryConstrainedWorkloadRoles"
    effect    = "Allow"
    actions   = ["iam:CreateRole"]
    resources = local.workload_role_resources

    condition {
      test     = "ArnEquals"
      variable = "iam:PermissionsBoundary"
      values   = [aws_iam_policy.workload_boundary.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = ["demo"]
    }
  }

  statement {
    sid    = "ManageOnlyExactWorkloadRoles"
    effect = "Allow"
    actions = [
      "iam:DeleteRole",
      "iam:DeleteRolePolicy",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
      "iam:PutRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:UpdateRole",
    ]
    resources = local.workload_role_resources
  }

  statement {
    sid    = "PassExactEcsRolesToEcsOnly"
    effect = "Allow"
    actions = [
      "iam:PassRole",
    ]
    resources = [
      local.workload_role_arns["ecs-execution"],
      local.workload_role_arns["api"],
      local.workload_role_arns["dashboard"],
      local.workload_role_arns["monitor"],
    ]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    sid       = "PassExactFirehoseRoleToFirehoseOnly"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [local.workload_role_arns["firehose"]]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["firehose.amazonaws.com"]
    }
  }

  statement {
    sid       = "PassExactSchedulerRoleToSchedulerOnly"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [local.workload_role_arns["scheduler"]]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "ci_plan_state" {
  name   = "remote-state-lock-read"
  role   = aws_iam_role.ci_plan.id
  policy = data.aws_iam_policy_document.remote_state_plan.json

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_policy" "ci_plan_read" {
  name        = "${var.project_name}-ci-plan-read"
  path        = local.bootstrap_path
  description = "Read-only Terraform refresh and verified teardown inventory for the exact demo"
  policy      = data.aws_iam_policy_document.ci_plan_read.json

  tags = merge(local.common_tags, { Name = "${var.project_name}-ci-plan-read" })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy_attachment" "ci_plan_read" {
  role       = aws_iam_role.ci_plan.name
  policy_arn = aws_iam_policy.ci_plan_read.arn

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy_attachment" "ci_deploy_read" {
  role       = aws_iam_role.ci_deploy.name
  policy_arn = aws_iam_policy.ci_plan_read.arn

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy" "ci_deploy_state" {
  name   = "remote-state-lock-write"
  role   = aws_iam_role.ci_deploy.id
  policy = data.aws_iam_policy_document.remote_state_deploy.json

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_policy" "ci_deploy_compute" {
  name        = "${var.project_name}-ci-deploy-compute"
  path        = local.bootstrap_path
  description = "Exact ECS/ALB and guarded EC2 lifecycle for the disposable demo"
  policy      = data.aws_iam_policy_document.ci_deploy_compute.json

  tags = merge(local.common_tags, { Name = "${var.project_name}-ci-deploy-compute" })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_policy" "ci_deploy_network_create" {
  name        = "${var.project_name}-ci-deploy-network-create"
  path        = local.bootstrap_path
  description = "Region-bound request-tagged creation of disposable demo network resources"
  policy      = data.aws_iam_policy_document.ci_deploy_network_create.json

  tags = merge(local.common_tags, { Name = "${var.project_name}-ci-deploy-network-create" })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_policy" "ci_deploy_network_dependencies" {
  name        = "${var.project_name}-ci-deploy-network-dependencies"
  path        = local.bootstrap_path
  description = "Tagged parent-resource authorization for demo NAT and VPC endpoint creation"
  policy      = data.aws_iam_policy_document.ci_deploy_network_dependencies.json

  tags = merge(local.common_tags, { Name = "${var.project_name}-ci-deploy-network-dependencies" })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_policy" "ci_deploy_network_lifecycle" {
  name        = "${var.project_name}-ci-deploy-network-lifecycle"
  path        = local.bootstrap_path
  description = "Region-bound lifecycle limited to tagged disposable demo network resources"
  policy      = data.aws_iam_policy_document.ci_deploy_network_lifecycle.json

  tags = merge(local.common_tags, { Name = "${var.project_name}-ci-deploy-network-lifecycle" })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_policy" "ci_deploy_boundary" {
  name        = "${var.project_name}-ci-deploy-boundary"
  path        = local.bootstrap_path
  description = "Defense-in-depth maximum permissions for the GitHub deploy role"
  policy      = data.aws_iam_policy_document.ci_deploy_boundary.json

  tags = merge(local.common_tags, { Name = "${var.project_name}-ci-deploy-boundary" })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_policy" "ci_deploy_data" {
  name        = "${var.project_name}-ci-deploy-data"
  path        = local.bootstrap_path
  description = "Exact demo S3, ECR, Firehose, and SSM lifecycle"
  policy      = data.aws_iam_policy_document.ci_deploy_data.json

  tags = merge(local.common_tags, { Name = "${var.project_name}-ci-deploy-data" })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_policy" "ci_deploy_operations" {
  name        = "${var.project_name}-ci-deploy-operations"
  path        = local.bootstrap_path
  description = "Exact demo logs, alarms, Scheduler, SNS, KMS metadata, and Budget lifecycle"
  policy      = data.aws_iam_policy_document.ci_deploy_operations.json

  tags = merge(local.common_tags, { Name = "${var.project_name}-ci-deploy-operations" })

  lifecycle {
    prevent_destroy = true
  }
}

locals {
  ci_deploy_managed_policy_arns = {
    compute              = aws_iam_policy.ci_deploy_compute.arn
    data                 = aws_iam_policy.ci_deploy_data.arn
    network_create       = aws_iam_policy.ci_deploy_network_create.arn
    network_dependencies = aws_iam_policy.ci_deploy_network_dependencies.arn
    network_lifecycle    = aws_iam_policy.ci_deploy_network_lifecycle.arn
    operations           = aws_iam_policy.ci_deploy_operations.arn
  }
}

resource "aws_iam_role_policy_attachment" "ci_deploy" {
  for_each = local.ci_deploy_managed_policy_arns

  role       = aws_iam_role.ci_deploy.name
  policy_arn = each.value

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy" "ci_deploy_iam" {
  name   = "boundary-constrained-workload-roles"
  role   = aws_iam_role.ci_deploy.id
  policy = data.aws_iam_policy_document.ci_deploy_iam.json

  lifecycle {
    prevent_destroy = true
  }
}
