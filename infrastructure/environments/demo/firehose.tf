resource "aws_kinesis_firehose_delivery_stream" "predictions" {
  # checkov:skip=CKV_AWS_241:AWS-owned Firehose encryption avoids a disposable customer key lingering after teardown; payloads are synthetic and destination S3 encryption is mandatory.

  name        = "${local.name_prefix}-predictions"
  destination = "extended_s3"

  server_side_encryption {
    enabled  = true
    key_type = "AWS_OWNED_CMK"
  }

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose.arn
    bucket_arn = module.data_plane.bucket_arns["predictions"]

    prefix = "predictions/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    error_output_prefix = (
      "errors/!{firehose:error-output-type}/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    )
    buffering_interval = 60
    buffering_size     = 5
    compression_format = "GZIP"
    custom_time_zone   = "UTC"

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose.name
      log_stream_name = aws_cloudwatch_log_stream.firehose.name
    }
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-predictions" })

  depends_on = [aws_iam_role_policy.firehose]
}
