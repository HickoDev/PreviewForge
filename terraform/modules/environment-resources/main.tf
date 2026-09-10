terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

variable "environment" { type = string }
variable "installation" { type = string }

locals {
  tags = {
    project      = "previewforge"
    environment  = var.environment
    managed_by   = "previewforge-m5"
    installation = var.installation
  }
}

resource "aws_s3_bucket" "reports" {
  bucket        = "previewforge-${var.environment}-reports"
  force_destroy = true # Only disposable synthetic reports; controller checks ownership first.
  tags          = local.tags
}

resource "aws_sqs_queue" "exports" {
  name                       = "previewforge-${var.environment}-exports"
  visibility_timeout_seconds = 30
  receive_wait_time_seconds  = 2
  message_retention_seconds  = 86400
  sqs_managed_sse_enabled    = false
  tags                       = local.tags
}

output "resources" {
  value = {
    bucket    = aws_s3_bucket.reports.id
    queue_url = aws_sqs_queue.exports.url
    queue_arn = aws_sqs_queue.exports.arn
  }
}
