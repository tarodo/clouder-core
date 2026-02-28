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
