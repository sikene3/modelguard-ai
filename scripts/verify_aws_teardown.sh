#!/usr/bin/env bash
set -euo pipefail

required_names=(EXPECTED_AWS_ACCOUNT_ID AWS_REGION INVENTORY_OUTPUT)
for required_name in "${required_names[@]}"; do
  if [[ -z "${!required_name:-}" ]]; then
    echo "Refusing inventory: $required_name is required."
    exit 1
  fi
done
if [[ ! "$EXPECTED_AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  echo "Refusing inventory: EXPECTED_AWS_ACCOUNT_ID must contain 12 digits."
  exit 1
fi

actual_account="$(aws sts get-caller-identity --query Account --output text)"
if [[ "$actual_account" != "$EXPECTED_AWS_ACCOUNT_ID" ]]; then
  echo "Refusing inventory: caller account does not match EXPECTED_AWS_ACCOUNT_ID."
  exit 1
fi
configured_region="$(aws configure get region)"
if [[ "$configured_region" != "$AWS_REGION" ]]; then
  echo "Refusing inventory: configured AWS Region does not match AWS_REGION."
  exit 1
fi

inventory_dir="$(mktemp -d)"
trap 'rm -rf -- "$inventory_dir"' EXIT
prefix="modelguard-ai-demo"
unique_prefix="$prefix-$EXPECTED_AWS_ACCOUNT_ID-$AWS_REGION"

write_empty_array() {
  printf '[]\n' > "$1"
}

append_json_array() {
  local target="$1"
  local fragment="$2"
  local merged="$inventory_dir/merged-array.json"
  jq -s 'add' "$target" "$fragment" > "$merged"
  mv "$merged" "$target"
}

aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=Project,Values=modelguard-ai Key=Environment,Values=demo \
  --output json > "$inventory_dir/tagged.json"

aws ecs list-clusters \
  --query "clusterArns[?ends_with(@, ':cluster/$prefix')]" \
  --output json > "$inventory_dir/ecs-clusters.json"
aws ecs list-task-definitions \
  --family-prefix "$prefix" \
  --status ACTIVE \
  --query taskDefinitionArns \
  --output json > "$inventory_dir/ecs-task-definitions-active.json"
aws ecs list-task-definitions \
  --family-prefix "$prefix" \
  --status INACTIVE \
  --query taskDefinitionArns \
  --output json > "$inventory_dir/ecs-task-definitions-inactive.json"
if jq -e 'length > 0' "$inventory_dir/ecs-clusters.json" >/dev/null; then
  aws ecs list-services \
    --cluster "$prefix" \
    --query serviceArns --output json > "$inventory_dir/ecs-services.json"
  aws ecs list-tasks \
    --cluster "$prefix" \
    --query taskArns --output json > "$inventory_dir/ecs-tasks.json"
else
  printf '[]\n' > "$inventory_dir/ecs-services.json"
  printf '[]\n' > "$inventory_dir/ecs-tasks.json"
fi
aws elbv2 describe-load-balancers \
  --query "LoadBalancers[?starts_with(LoadBalancerName, '$prefix')].LoadBalancerArn" \
  --output json > "$inventory_dir/load-balancers.json"
write_empty_array "$inventory_dir/listeners.json"
write_empty_array "$inventory_dir/listener-rules.json"
mapfile -t load_balancer_arns < <(jq -r '.[]' "$inventory_dir/load-balancers.json")
for index in "${!load_balancer_arns[@]}"; do
  load_balancer_arn="${load_balancer_arns[$index]}"
  aws elbv2 describe-listeners \
    --load-balancer-arn "$load_balancer_arn" \
    --query 'Listeners[].ListenerArn' \
    --output json > "$inventory_dir/listeners-$index.json"
  append_json_array "$inventory_dir/listeners.json" "$inventory_dir/listeners-$index.json"
done
mapfile -t listener_arns < <(jq -r '.[]' "$inventory_dir/listeners.json")
for index in "${!listener_arns[@]}"; do
  listener_arn="${listener_arns[$index]}"
  aws elbv2 describe-rules \
    --listener-arn "$listener_arn" \
    --query 'Rules[].RuleArn' \
    --output json > "$inventory_dir/listener-rules-$index.json"
  append_json_array "$inventory_dir/listener-rules.json" "$inventory_dir/listener-rules-$index.json"
done
aws elbv2 describe-target-groups \
  --query "TargetGroups[?starts_with(TargetGroupName, '$prefix')].TargetGroupArn" \
  --output json > "$inventory_dir/target-groups.json"
aws ec2 describe-vpcs \
  --filters Name=tag:Project,Values=modelguard-ai Name=tag:Environment,Values=demo \
  --query 'Vpcs[].VpcId' --output json > "$inventory_dir/vpcs.json"
# The backticks delimit a JMESPath literal; single quotes intentionally prevent shell expansion.
# shellcheck disable=SC2016
aws ec2 describe-nat-gateways \
  --filter Name=tag:Project,Values=modelguard-ai Name=tag:Environment,Values=demo \
  --query 'NatGateways[?State != `deleted`].NatGatewayId' \
  --output json > "$inventory_dir/nat-gateways.json"
aws ec2 describe-addresses \
  --filters Name=tag:Project,Values=modelguard-ai Name=tag:Environment,Values=demo \
  --query 'Addresses[].AllocationId' --output json > "$inventory_dir/eips.json"
aws ec2 describe-vpc-endpoints \
  --filters Name=tag:Project,Values=modelguard-ai Name=tag:Environment,Values=demo \
  --query 'VpcEndpoints[].VpcEndpointId' --output json > "$inventory_dir/vpc-endpoints.json"
aws ec2 describe-subnets \
  --filters Name=tag:Project,Values=modelguard-ai Name=tag:Environment,Values=demo \
  --query 'Subnets[].SubnetId' --output json > "$inventory_dir/subnets.json"
aws ec2 describe-route-tables \
  --filters Name=tag:Project,Values=modelguard-ai Name=tag:Environment,Values=demo \
  --query 'RouteTables[].RouteTableId' --output json > "$inventory_dir/route-tables.json"
aws ec2 describe-security-groups \
  --filters Name=tag:Project,Values=modelguard-ai Name=tag:Environment,Values=demo \
  --query 'SecurityGroups[].GroupId' --output json > "$inventory_dir/security-groups.json"
aws ec2 describe-internet-gateways \
  --filters Name=tag:Project,Values=modelguard-ai Name=tag:Environment,Values=demo \
  --query 'InternetGateways[].InternetGatewayId' \
  --output json > "$inventory_dir/internet-gateways.json"
aws s3api list-buckets \
  --query "Buckets[?starts_with(Name, '$unique_prefix-')].Name" \
  --output json > "$inventory_dir/s3-buckets.json"
write_empty_array "$inventory_dir/s3-object-versions.json"
write_empty_array "$inventory_dir/s3-multipart-uploads.json"
mapfile -t demo_buckets < <(jq -r '.[]' "$inventory_dir/s3-buckets.json")
for index in "${!demo_buckets[@]}"; do
  bucket="${demo_buckets[$index]}"
  aws s3api list-object-versions \
    --bucket "$bucket" \
    --output json > "$inventory_dir/s3-object-versions-raw-$index.json"
  jq --arg bucket "$bucket" \
    '[((.Versions // []) + (.DeleteMarkers // []))[] | "\($bucket)/\(.Key)?versionId=\(.VersionId)"]' \
    "$inventory_dir/s3-object-versions-raw-$index.json" \
    > "$inventory_dir/s3-object-versions-$index.json"
  append_json_array \
    "$inventory_dir/s3-object-versions.json" \
    "$inventory_dir/s3-object-versions-$index.json"

  aws s3api list-multipart-uploads \
    --bucket "$bucket" \
    --output json > "$inventory_dir/s3-multipart-uploads-raw-$index.json"
  jq --arg bucket "$bucket" \
    '[(.Uploads // [])[] | "\($bucket)/\(.Key)?uploadId=\(.UploadId)"]' \
    "$inventory_dir/s3-multipart-uploads-raw-$index.json" \
    > "$inventory_dir/s3-multipart-uploads-$index.json"
  append_json_array \
    "$inventory_dir/s3-multipart-uploads.json" \
    "$inventory_dir/s3-multipart-uploads-$index.json"
done

aws ecr describe-repositories --output json > "$inventory_dir/ecr-describe.json"
jq '[.repositories[]? | select(.repositoryName | startswith("modelguard-ai/demo/")) | .repositoryArn]' \
  "$inventory_dir/ecr-describe.json" > "$inventory_dir/ecr-repositories.json"
jq '[.repositories[]? | select(.repositoryName | startswith("modelguard-ai/demo/")) | .repositoryName]' \
  "$inventory_dir/ecr-describe.json" > "$inventory_dir/ecr-repository-names.json"
write_empty_array "$inventory_dir/ecr-images.json"
mapfile -t ecr_repository_names < <(jq -r '.[]' "$inventory_dir/ecr-repository-names.json")
for index in "${!ecr_repository_names[@]}"; do
  repository_name="${ecr_repository_names[$index]}"
  aws ecr list-images \
    --repository-name "$repository_name" \
    --query imageIds \
    --output json > "$inventory_dir/ecr-images-raw-$index.json"
  jq --arg repository "$repository_name" \
    '[.[] | $repository + "@" + (.imageDigest // "no-digest") + (if .imageTag then ":" + .imageTag else "" end)]' \
    "$inventory_dir/ecr-images-raw-$index.json" > "$inventory_dir/ecr-images-$index.json"
  append_json_array "$inventory_dir/ecr-images.json" "$inventory_dir/ecr-images-$index.json"
done
aws firehose list-delivery-streams \
  --query "DeliveryStreamNames[?starts_with(@, '$prefix')]" \
  --output json > "$inventory_dir/firehose.json"
aws scheduler list-schedule-groups \
  --name-prefix "$prefix" \
  --query 'ScheduleGroups[].Arn' --output json > "$inventory_dir/scheduler-groups.json"
if jq -e 'length > 0' "$inventory_dir/scheduler-groups.json" >/dev/null; then
  aws scheduler list-schedules \
    --group-name "$prefix-monitor" \
    --query 'Schedules[].Arn' --output json > "$inventory_dir/schedules.json"
else
  printf '[]\n' > "$inventory_dir/schedules.json"
fi
aws logs describe-log-groups \
  --log-group-name-prefix "/modelguard-ai/demo/" \
  --query 'logGroups[].arn' --output json > "$inventory_dir/log-groups.json"
aws cloudwatch describe-alarms \
  --alarm-name-prefix "$prefix" \
  --query 'MetricAlarms[].AlarmArn' --output json > "$inventory_dir/alarms.json"
aws sns list-topics \
  --query "Topics[?ends_with(TopicArn, ':$prefix-alerts')].TopicArn" \
  --output json > "$inventory_dir/sns-topics.json"
write_empty_array "$inventory_dir/sns-subscriptions.json"
mapfile -t sns_topic_arns < <(jq -r '.[]' "$inventory_dir/sns-topics.json")
for index in "${!sns_topic_arns[@]}"; do
  topic_arn="${sns_topic_arns[$index]}"
  aws sns list-subscriptions-by-topic \
    --topic-arn "$topic_arn" \
    --query 'Subscriptions[].SubscriptionArn' \
    --output json > "$inventory_dir/sns-subscriptions-$index.json"
  append_json_array \
    "$inventory_dir/sns-subscriptions.json" \
    "$inventory_dir/sns-subscriptions-$index.json"
done
aws ssm describe-parameters \
  --parameter-filters "Key=Name,Option=BeginsWith,Values=/modelguard-ai/demo/models/" \
  --query 'Parameters[].Name' --output json > "$inventory_dir/ssm-pointers.json"
aws iam list-roles \
  --path-prefix /modelguard-ai/demo/ \
  --query 'Roles[].Arn' --output json > "$inventory_dir/workload-roles.json"
aws budgets describe-budgets \
  --account-id "$EXPECTED_AWS_ACCOUNT_ID" \
  --query "Budgets[?BudgetName == '$prefix-monthly'].BudgetName" \
  --output json > "$inventory_dir/budgets.json"

jq -n \
  --argjson tagged "$(jq '.ResourceTagMappingList' "$inventory_dir/tagged.json")" \
  --argjson ecs_clusters "$(cat "$inventory_dir/ecs-clusters.json")" \
  --argjson ecs_task_definitions_active "$(cat "$inventory_dir/ecs-task-definitions-active.json")" \
  --argjson ecs_task_definitions_inactive "$(cat "$inventory_dir/ecs-task-definitions-inactive.json")" \
  --argjson ecs_services "$(cat "$inventory_dir/ecs-services.json")" \
  --argjson ecs_tasks "$(cat "$inventory_dir/ecs-tasks.json")" \
  --argjson load_balancers "$(cat "$inventory_dir/load-balancers.json")" \
  --argjson listeners "$(cat "$inventory_dir/listeners.json")" \
  --argjson listener_rules "$(cat "$inventory_dir/listener-rules.json")" \
  --argjson target_groups "$(cat "$inventory_dir/target-groups.json")" \
  --argjson vpcs "$(cat "$inventory_dir/vpcs.json")" \
  --argjson nat_gateways "$(cat "$inventory_dir/nat-gateways.json")" \
  --argjson eips "$(cat "$inventory_dir/eips.json")" \
  --argjson vpc_endpoints "$(cat "$inventory_dir/vpc-endpoints.json")" \
  --argjson subnets "$(cat "$inventory_dir/subnets.json")" \
  --argjson route_tables "$(cat "$inventory_dir/route-tables.json")" \
  --argjson security_groups "$(cat "$inventory_dir/security-groups.json")" \
  --argjson internet_gateways "$(cat "$inventory_dir/internet-gateways.json")" \
  --argjson s3_buckets "$(cat "$inventory_dir/s3-buckets.json")" \
  --argjson s3_object_versions "$(cat "$inventory_dir/s3-object-versions.json")" \
  --argjson s3_multipart_uploads "$(cat "$inventory_dir/s3-multipart-uploads.json")" \
  --argjson ecr_repositories "$(cat "$inventory_dir/ecr-repositories.json")" \
  --argjson ecr_images "$(cat "$inventory_dir/ecr-images.json")" \
  --argjson firehose "$(cat "$inventory_dir/firehose.json")" \
  --argjson scheduler_groups "$(cat "$inventory_dir/scheduler-groups.json")" \
  --argjson schedules "$(cat "$inventory_dir/schedules.json")" \
  --argjson log_groups "$(cat "$inventory_dir/log-groups.json")" \
  --argjson alarms "$(cat "$inventory_dir/alarms.json")" \
  --argjson sns_topics "$(cat "$inventory_dir/sns-topics.json")" \
  --argjson sns_subscriptions "$(cat "$inventory_dir/sns-subscriptions.json")" \
  --argjson ssm_pointers "$(cat "$inventory_dir/ssm-pointers.json")" \
  --argjson workload_roles "$(cat "$inventory_dir/workload-roles.json")" \
  --argjson budgets "$(cat "$inventory_dir/budgets.json")" \
  '{
    schema_version: "modelguard.post-destroy-inventory.v1",
    ResourceTagMappingList: $tagged,
    service_residuals: {
      ecs_clusters: $ecs_clusters,
      ecs_task_definitions_active: $ecs_task_definitions_active,
      ecs_task_definitions_inactive: $ecs_task_definitions_inactive,
      ecs_services: $ecs_services,
      ecs_tasks: $ecs_tasks,
      load_balancers: $load_balancers,
      listeners: $listeners,
      listener_rules: $listener_rules,
      target_groups: $target_groups,
      vpcs: $vpcs,
      nat_gateways: $nat_gateways,
      eips: $eips,
      vpc_endpoints: $vpc_endpoints,
      subnets: $subnets,
      route_tables: $route_tables,
      security_groups: $security_groups,
      internet_gateways: $internet_gateways,
      s3_buckets: $s3_buckets,
      s3_object_versions: $s3_object_versions,
      s3_multipart_uploads: $s3_multipart_uploads,
      ecr_repositories: $ecr_repositories,
      ecr_images: $ecr_images,
      firehose_streams: $firehose,
      scheduler_groups: $scheduler_groups,
      scheduler_schedules: $schedules,
      log_groups: $log_groups,
      alarms: $alarms,
      sns_topics: $sns_topics,
      sns_subscriptions: $sns_subscriptions,
      ssm_pointers: $ssm_pointers,
      workload_roles: $workload_roles,
      budgets: $budgets
    }
  }' > "$INVENTORY_OUTPUT"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
uv run --frozen --no-sync python "$repo_root/scripts/terraform_demo_guard.py" \
  verify-inventory --input "$INVENTORY_OUTPUT"
