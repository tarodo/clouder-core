variable "project" {
  description = "Project name prefix for AWS resources"
  type        = string
  default     = "beatport"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "raw_prefix" {
  description = "S3 key prefix for raw Beatport data"
  type        = string
  default     = "raw/bp/releases"
}

variable "beatport_api_base_url" {
  description = "Beatport API base URL"
  type        = string
  default     = "https://api.beatport.com/v4/catalog"
}

variable "lambda_timeout_seconds" {
  description = "Collector Lambda timeout in seconds"
  type        = number
  default     = 120
}

variable "lambda_memory_mb" {
  description = "Collector Lambda memory size in MB"
  type        = number
  default     = 512
}

variable "log_retention_days" {
  description = "CloudWatch log retention period"
  type        = number
  default     = 30
}

variable "lambda_zip_path" {
  description = "Path to packaged Lambda ZIP, relative to repository root"
  type        = string
  default     = "dist/collector.zip"
}

variable "raw_bucket_name" {
  description = "Optional explicit S3 bucket name. If empty, a generated name is used"
  type        = string
  default     = ""
}

variable "canonicalize_enabled" {
  description = "Enable enqueueing canonicalization messages from the API lambda"
  type        = bool
  default     = false
}

variable "canonicalize_queue_visibility_timeout_seconds" {
  description = "Visibility timeout for canonicalization queue"
  type        = number
  default     = 180
}

variable "canonicalize_queue_retention_seconds" {
  description = "Message retention for canonicalization queue"
  type        = number
  default     = 1209600
}

variable "canonicalizer_batch_size" {
  description = "SQS batch size for canonicalizer lambda"
  type        = number
  default     = 1
}

variable "worker_lambda_timeout_seconds" {
  description = "Canonicalization worker Lambda timeout in seconds"
  type        = number
  default     = 900
}

variable "worker_lambda_memory_mb" {
  description = "Canonicalization worker Lambda memory size in MB"
  type        = number
  default     = 1024
}

variable "aurora_database_name" {
  description = "Initial Aurora PostgreSQL database name"
  type        = string
  default     = "clouder"
}

variable "aurora_engine_version" {
  description = "Aurora PostgreSQL engine version"
  type        = string
  default     = "16.6"
}

variable "aurora_master_username" {
  description = "Master username for Aurora PostgreSQL"
  type        = string
  default     = "clouder_admin"
}

variable "aurora_serverless_min_acu" {
  description = "Aurora Serverless v2 min ACU"
  type        = number
  default     = 0
}

variable "aurora_serverless_max_acu" {
  description = "Aurora Serverless v2 max ACU"
  type        = number
  default     = 2
}

variable "aurora_auto_pause_seconds" {
  description = "Aurora Serverless v2 seconds until auto pause"
  type        = number
  default     = 300
}

variable "vpc_cidr" {
  description = "CIDR for VPC used by Aurora"
  type        = string
  default     = "10.60.0.0/16"
}

variable "private_subnet_a_cidr" {
  description = "CIDR for first subnet used by Aurora"
  type        = string
  default     = "10.60.1.0/24"
}

variable "private_subnet_b_cidr" {
  description = "CIDR for second subnet used by Aurora"
  type        = string
  default     = "10.60.2.0/24"
}
