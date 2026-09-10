terraform {
  required_version = "= 1.16.2"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.64.0"
    }
  }
}

provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  token                       = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  skip_region_validation      = true
  s3_use_path_style           = true
  shared_config_files         = []
  shared_credentials_files    = []
  endpoints {
    s3  = var.endpoint
    sqs = var.endpoint
    sts = var.endpoint
    iam = var.endpoint
  }
}

variable "endpoint" {
  type = string
  validation {
    condition     = contains(["http://127.0.0.1:4566", "http://floci:4566"], var.endpoint)
    error_message = "Terraform is restricted to the explicit local Floci endpoint."
  }
}

variable "environment" {
  type = string
  validation {
    condition     = can(regex("^(staging|local|test|preview-[1-9][0-9]{0,8})$", var.environment))
    error_message = "Use an owned PreviewForge environment."
  }
}

variable "installation" {
  type = string
  validation {
    condition     = can(regex("^[a-f0-9]{32}$", var.installation))
    error_message = "The local reconciler must supply its persistent installation identity."
  }
}

module "environment" {
  source       = "../../modules/environment-resources"
  environment  = var.environment
  installation = var.installation
}

output "resources" {
  value = module.environment.resources
}
