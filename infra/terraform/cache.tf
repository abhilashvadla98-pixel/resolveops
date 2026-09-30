resource "aws_elasticache_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_replication_group" "coordination" {
  replication_group_id = substr("${local.name}-coordination", 0, 40)
  description          = "ResolveOps queue wake-up and shared rate-limit coordination"

  engine         = "valkey"
  engine_version = "7.2"
  node_type      = var.cache_node_type
  port           = 6379

  num_cache_clusters         = var.cache_multi_az ? 2 : 1
  automatic_failover_enabled = var.cache_multi_az
  multi_az_enabled           = var.cache_multi_az

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.cache.id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  transit_encryption_mode    = "required"
  apply_immediately          = false

  snapshot_retention_limit   = 1
  auto_minor_version_upgrade = true

  tags = { Name = "${local.name}-coordination" }
}
