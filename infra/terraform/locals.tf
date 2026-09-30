locals {
  name = "${var.project_name}-${var.environment}"

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "Terraform"
  }

  database_environment = [
    {
      name  = "RESOLVEOPS_ENVIRONMENT"
      value = "production"
    },
    {
      name  = "RESOLVEOPS_DATABASE_HOST"
      value = aws_db_instance.main.address
    },
    {
      name  = "RESOLVEOPS_DATABASE_PORT"
      value = tostring(aws_db_instance.main.port)
    },
    {
      name  = "RESOLVEOPS_DATABASE_NAME"
      value = var.database_name
    },
    {
      name  = "RESOLVEOPS_DEFAULT_TENANT_ID"
      value = "TENANT-PRODUCTION"
    },
    {
      name  = "RESOLVEOPS_REDIS_URL"
      value = "rediss://${aws_elasticache_replication_group.coordination.primary_endpoint_address}:6379/0"
    },
    {
      name  = "RESOLVEOPS_AGENT_QUEUE_ENABLED"
      value = "true"
    }
  ]

  application_secrets = [
    {
      name      = "RESOLVEOPS_DATABASE_USERNAME"
      valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:username::"
    },
    {
      name      = "RESOLVEOPS_DATABASE_PASSWORD"
      valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::"
    },
    {
      name      = "RESOLVEOPS_API_KEY_IDENTITIES_JSON"
      valueFrom = "${var.application_secret_arn}:api_key_identities_json::"
    },
    {
      name      = "RESOLVEOPS_WEBHOOK_SECRET"
      valueFrom = "${var.application_secret_arn}:webhook_secret::"
    },
    {
      name      = "RESOLVEOPS_GEMINI_API_KEY"
      valueFrom = "${var.application_secret_arn}:gemini_api_key::"
    }
  ]
}
