locals {
  environment = [
    for name in sort(keys(var.environment)) : {
      name  = name
      value = var.environment[name]
    }
  ]
  secrets = [
    for secret in var.secrets : {
      name      = secret.name
      valueFrom = secret.value_from
    }
  ]
  mount_points = concat(
    [{
      sourceVolume  = "scratch"
      containerPath = "/tmp"
      readOnly      = false
    }],
    var.writable_mount_path == null ? [] : [{
      sourceVolume  = "runtime"
      containerPath = var.writable_mount_path
      readOnly      = false
    }],
  )
}

resource "aws_ecs_task_definition" "this" {
  family                   = var.family
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.cpu)
  memory                   = tostring(var.memory)
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  volume {
    name = "scratch"
  }

  dynamic "volume" {
    for_each = var.writable_mount_path == null ? [] : [1]
    content {
      name = "runtime"
    }
  }

  container_definitions = jsonencode([
    {
      name                   = var.name
      image                  = var.image_ref
      essential              = true
      user                   = "10001:10001"
      readonlyRootFilesystem = true
      privileged             = false
      cpu                    = var.cpu
      memory                 = var.memory
      stopTimeout            = 30
      portMappings = [{
        name          = "${var.name}-http"
        containerPort = var.container_port
        hostPort      = var.container_port
        protocol      = "tcp"
        appProtocol   = "http"
      }]
      environment = local.environment
      secrets     = local.secrets
      mountPoints = local.mount_points
      healthCheck = {
        command     = var.health_check_command
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
      linuxParameters = {
        initProcessEnabled = true
        capabilities = {
          add  = []
          drop = ["ALL"]
        }
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = var.log_group_name
          awslogs-region        = var.region
          awslogs-stream-prefix = var.name
          mode                  = "non-blocking"
          max-buffer-size       = "1m"
        }
      }
    }
  ])

  tags = merge(var.tags, { Component = var.name })
}

resource "aws_ecs_service" "this" {
  name             = var.family
  cluster          = var.cluster_arn
  task_definition  = aws_ecs_task_definition.this.arn
  desired_count    = var.desired_count
  launch_type      = "FARGATE"
  platform_version = "LATEST"

  enable_ecs_managed_tags = true
  enable_execute_command  = false
  propagate_tags          = "SERVICE"

  health_check_grace_period_seconds  = 60
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_controller {
    type = "ECS"
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = var.name
    container_port   = var.container_port
  }

  tags = merge(var.tags, { Component = var.name })
}
