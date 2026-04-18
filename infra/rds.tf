resource "aws_rds_cluster" "aurora" {
  cluster_identifier = local.db_cluster_identifier
  engine             = "aurora-postgresql"
  engine_version     = var.aurora_engine_version

  database_name                       = var.aurora_database_name
  master_username                     = var.aurora_master_username
  manage_master_user_password         = true
  iam_database_authentication_enabled = true

  db_subnet_group_name   = aws_db_subnet_group.aurora.name
  vpc_security_group_ids = [aws_security_group.aurora.id]

  enable_http_endpoint  = true
  storage_encrypted     = true
  copy_tags_to_snapshot = true

  skip_final_snapshot = true
  deletion_protection = false

  serverlessv2_scaling_configuration {
    min_capacity             = var.aurora_serverless_min_acu
    max_capacity             = var.aurora_serverless_max_acu
    seconds_until_auto_pause = var.aurora_auto_pause_seconds
  }
}

resource "aws_rds_cluster_instance" "aurora_writer" {
  identifier          = "${local.db_cluster_identifier}-writer"
  cluster_identifier  = aws_rds_cluster.aurora.id
  instance_class      = "db.serverless"
  engine              = aws_rds_cluster.aurora.engine
  engine_version      = aws_rds_cluster.aurora.engine_version
  publicly_accessible = false
}
