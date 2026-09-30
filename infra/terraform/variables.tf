variable "project_name" {
  description = "Short lowercase project name used in AWS resource names."
  type        = string
  default     = "resolveops"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,20}$", var.project_name))
    error_message = "project_name must be 3-21 lowercase letters, numbers, or hyphens."
  }
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "production"
}

variable "aws_region" {
  description = "AWS region for all regional resources."
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  description = "CIDR block for the deployment VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "image_tag" {
  description = "Immutable container image tag, normally the Git commit SHA."
  type        = string
}

variable "application_secret_arn" {
  description = "Existing Secrets Manager secret with api_key_identities_json and webhook_secret keys."
  type        = string
  sensitive   = true
}

variable "certificate_arn" {
  description = "Optional ACM certificate ARN. When omitted, the ALB serves HTTP for initial testing."
  type        = string
  default     = null
  nullable    = true
}

variable "database_name" {
  description = "PostgreSQL database name."
  type        = string
  default     = "resolveops"
}

variable "database_username" {
  description = "PostgreSQL master username; its password is managed by RDS in Secrets Manager."
  type        = string
  default     = "resolveopsadmin"
}

variable "database_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "database_multi_az" {
  description = "Enable an RDS standby in another Availability Zone."
  type        = bool
  default     = false
}

variable "database_deletion_protection" {
  description = "Protect the RDS instance from accidental deletion."
  type        = bool
  default     = true
}

variable "api_desired_count" {
  description = "API task count applied by the deployment workflow after migrations succeed."
  type        = number
  default     = 2

  validation {
    condition     = var.api_desired_count >= 1 && var.api_desired_count <= 10
    error_message = "api_desired_count must be between 1 and 10."
  }
}

variable "worker_desired_count" {
  description = "Background agent worker task count applied after migrations succeed."
  type        = number
  default     = 1

  validation {
    condition     = var.worker_desired_count >= 1 && var.worker_desired_count <= 10
    error_message = "worker_desired_count must be between 1 and 10."
  }
}

variable "cache_node_type" {
  description = "ElastiCache node type for queue wake-up and shared rate-limit coordination."
  type        = string
  default     = "cache.t4g.micro"
}

variable "cache_multi_az" {
  description = "Create a Valkey replica with automatic failover in another Availability Zone."
  type        = bool
  default     = false
}

variable "container_cpu" {
  description = "Fargate CPU units for each API and migration task."
  type        = number
  default     = 512
}

variable "container_memory" {
  description = "Fargate memory in MiB for each API and migration task."
  type        = number
  default     = 1024
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 30
}

variable "alarm_email" {
  description = "Optional email address for CloudWatch alarm notifications."
  type        = string
  default     = null
  nullable    = true
}
