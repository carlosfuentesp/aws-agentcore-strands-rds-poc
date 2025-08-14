output "db_secret_arn" {
  value = aws_secretsmanager_secret.db_master.arn
}

output "aurora_cluster_arn" {
  value = aws_rds_cluster.this.arn
}

output "aurora_cluster_id" {
  value = aws_rds_cluster.this.id
}

output "region" {
  value = var.region
}