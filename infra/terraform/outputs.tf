output "application_url" {
  description = "Public ResolveOps URL. Configure certificate_arn for HTTPS."
  value = (
    var.certificate_arn == null
    ? "http://${aws_lb.main.dns_name}"
    : "https://${aws_lb.main.dns_name}"
  )
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  value = aws_ecs_service.api.name
}

output "api_task_definition_arn" {
  value = aws_ecs_task_definition.api.arn
}

output "migration_task_definition_arn" {
  value = aws_ecs_task_definition.migration.arn
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "ecs_security_group_id" {
  value = aws_security_group.ecs.id
}

output "api_desired_count" {
  value = var.api_desired_count
}

output "alarm_topic_arn" {
  value = aws_sns_topic.alarms.arn
}
