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

variable "canonicalization_enabled" {
  description = "Enable enqueueing canonicalization messages from the API lambda"
  type        = bool
  default     = false
}

variable "canonicalization_queue_visibility_timeout_seconds" {
  description = "Visibility timeout for canonicalization queue (effective value is max(this, worker lambda timeout))"
  type        = number
  default     = 180
}

variable "canonicalization_queue_retention_seconds" {
  description = "Message retention for canonicalization queue"
  type        = number
  default     = 1209600
}

variable "canonicalization_batch_size" {
  description = "SQS batch size for canonicalization worker lambda"
  type        = number
  default     = 1
}

variable "canonicalization_worker_lambda_timeout_seconds" {
  description = "Canonicalization worker Lambda timeout in seconds"
  type        = number
  default     = 900
}

variable "canonicalization_worker_lambda_memory_mb" {
  description = "Canonicalization worker Lambda memory size in MB"
  type        = number
  default     = 1024
}

variable "migration_lambda_timeout_seconds" {
  description = "DB migration Lambda timeout in seconds"
  type        = number
  default     = 900
}

variable "migration_lambda_memory_mb" {
  description = "DB migration Lambda memory size in MB"
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

variable "enable_secretsmanager_vpc_endpoint" {
  description = "Create a temporary VPC interface endpoint for Secrets Manager (needed only during DB migrations in private subnets)"
  type        = bool
  default     = false
}

# ── AI Search ──────────────────────────────────────────────────────

variable "ai_search_enabled" {
  description = "Enable AI-powered label search via Perplexity"
  type        = bool
  default     = false
}

variable "ai_search_worker_lambda_timeout_seconds" {
  description = "AI search worker Lambda timeout in seconds"
  type        = number
  default     = 60
}

variable "ai_search_worker_lambda_memory_mb" {
  description = "AI search worker Lambda memory size in MB"
  type        = number
  default     = 256
}

variable "ai_search_batch_size" {
  description = "SQS batch size for AI search worker lambda"
  type        = number
  default     = 1
}

variable "ai_search_queue_visibility_timeout_seconds" {
  description = "Visibility timeout for AI search queue"
  type        = number
  default     = 90
}

variable "ai_search_queue_retention_seconds" {
  description = "Message retention for AI search queue"
  type        = number
  default     = 1209600
}

variable "perplexity_api_key_secret_arn" {
  description = "Legacy Secrets Manager ARN for the Perplexity API key. Empty when SSM is used."
  type        = string
  default     = ""

  validation {
    condition     = var.perplexity_api_key_secret_arn == "" || can(regex("^arn:aws:secretsmanager:", var.perplexity_api_key_secret_arn))
    error_message = "perplexity_api_key_secret_arn must be empty or a valid Secrets Manager ARN."
  }
}

# ── Spotify Search ────────────────────────────────────────────────

variable "spotify_search_enabled" {
  description = "Enable Spotify ISRC search after canonicalization"
  type        = bool
  default     = false
}

variable "spotify_credentials_secret_arn" {
  description = "Secrets Manager ARN for Spotify credentials (SecretString is JSON: {client_id, client_secret}). Empty when SSM is used."
  type        = string
  default     = ""

  validation {
    condition     = var.spotify_credentials_secret_arn == "" || can(regex("^arn:aws:secretsmanager:", var.spotify_credentials_secret_arn))
    error_message = "spotify_credentials_secret_arn must be empty or a valid Secrets Manager ARN."
  }
}

variable "spotify_raw_prefix" {
  description = "S3 key prefix for raw Spotify search results"
  type        = string
  default     = "raw/sp/tracks"
}

variable "spotify_search_worker_lambda_timeout_seconds" {
  description = "Spotify search worker Lambda timeout in seconds"
  type        = number
  default     = 900
}

variable "spotify_search_worker_lambda_memory_mb" {
  description = "Spotify search worker Lambda memory size in MB"
  type        = number
  default     = 512
}

variable "spotify_search_batch_size" {
  description = "SQS batch size for Spotify search worker lambda"
  type        = number
  default     = 1
}

variable "spotify_search_queue_visibility_timeout_seconds" {
  description = "Visibility timeout for Spotify search queue"
  type        = number
  default     = 960
}

variable "spotify_search_queue_retention_seconds" {
  description = "Message retention for Spotify search queue"
  type        = number
  default     = 1209600
}

variable "alarm_sns_topic_arn" {
  description = "SNS topic ARN to send DLQ depth alarms to. Empty string disables alarm actions."
  type        = string
  default     = ""
}

variable "perplexity_api_key_ssm_parameter" {
  description = "SSM Parameter Store name (SecureString) holding the Perplexity API key. Takes precedence over perplexity_api_key_secret_arn."
  type        = string
  default     = ""
}

variable "spotify_client_id_ssm_parameter" {
  description = "SSM Parameter Store name (SecureString) holding the Spotify client_id."
  type        = string
  default     = ""
}

variable "spotify_client_secret_ssm_parameter" {
  description = "SSM Parameter Store name (SecureString) holding the Spotify client_secret."
  type        = string
  default     = ""
}

# ── Vendor Match ──────────────────────────────────────────────────

variable "vendor_match_enabled" {
  description = "Enable the vendor match worker (per-track Spotify/YTM/Deezer/Apple/Tidal resolution)"
  type        = bool
  default     = false
}

variable "vendor_match_worker_lambda_timeout_seconds" {
  description = "Vendor match worker Lambda timeout in seconds"
  type        = number
  default     = 120
}

variable "vendor_match_worker_lambda_memory_mb" {
  description = "Vendor match worker Lambda memory size in MB"
  type        = number
  default     = 512
}

variable "vendor_match_batch_size" {
  description = "SQS batch size for vendor match worker lambda"
  type        = number
  default     = 1
}

variable "vendor_match_queue_visibility_timeout_seconds" {
  description = "Visibility timeout for vendor match queue (effective value is max(this, worker lambda timeout))"
  type        = number
  default     = 180
}

variable "vendor_match_queue_retention_seconds" {
  description = "Message retention for vendor match queue"
  type        = number
  default     = 1209600
}

variable "vendor_match_max_receive_count" {
  description = "Max receive count before a vendor match message goes to DLQ"
  type        = number
  default     = 5
}

variable "vendor_match_vendors_enabled" {
  description = "Comma-separated list of vendors enabled for the vendor_match worker"
  type        = string
  default     = ""
}

variable "fuzzy_match_threshold" {
  description = "Minimum fuzzy score to accept a metadata match (0..1)"
  type        = number
  default     = 0.92
}

variable "fuzzy_duration_tolerance_ms" {
  description = "Duration mismatch tolerance in ms for fuzzy match duration_ok flag"
  type        = number
  default     = 3000
}

variable "migration_db_user" {
  description = "PostgreSQL role name used by the migration Lambda when AURORA_AUTH_MODE=iam. Must have rds_iam granted."
  type        = string
  default     = "clouder_migrator"
}

variable "migration_aurora_auth_mode" {
  description = "Auth mode for the migration Lambda: 'password' (default, reads AURORA_SECRET_ARN from Secrets Manager) or 'iam' (generates an RDS IAM token)."
  type        = string
  default     = "password"

  validation {
    condition     = contains(["password", "iam"], var.migration_aurora_auth_mode)
    error_message = "migration_aurora_auth_mode must be either 'password' or 'iam'."
  }
}

# ── Spec-A user auth ───────────────────────────────────────────────

variable "admin_spotify_ids" {
  description = "Comma-separated list of Spotify user IDs that get is_admin=true on login"
  type        = string
  default     = ""
}

variable "spotify_oauth_redirect_uri" {
  description = "Full URL Spotify redirects to after consent (must be registered in the Spotify Developer Dashboard)"
  type        = string
}

variable "jwt_signing_key_ssm_parameter" {
  description = "SSM Parameter Store name (SecureString) holding the HS256 secret for JWTs"
  type        = string
  default     = "/clouder/auth/jwt_signing_key"
}

variable "allowed_frontend_redirects" {
  description = "Comma-separated allow-list of relative redirect_uri paths accepted by /auth/login"
  type        = string
  default     = "/"
}

variable "jwt_access_token_ttl_seconds" {
  description = "Access-token TTL"
  type        = number
  default     = 1800
}

variable "jwt_refresh_token_ttl_seconds" {
  description = "Refresh-token TTL"
  type        = number
  default     = 604800
}

variable "auth_handler_lambda_timeout_seconds" {
  description = "Auth Lambda timeout (seconds)"
  type        = number
  default     = 30
}

variable "auth_handler_lambda_memory_mb" {
  description = "Auth Lambda memory size in MB"
  type        = number
  default     = 512
}

variable "auth_authorizer_lambda_timeout_seconds" {
  description = "Authorizer Lambda timeout (seconds)"
  type        = number
  default     = 5
}

variable "auth_authorizer_lambda_memory_mb" {
  description = "Authorizer Lambda memory size in MB"
  type        = number
  default     = 256
}

variable "auth_authorizer_cache_ttl_seconds" {
  description = "API Gateway authorizer result-cache TTL (seconds)"
  type        = number
  default     = 300
}

variable "curation_lambda_timeout_seconds" {
  type        = number
  default     = 30
  description = "Curation Lambda timeout (seconds)"
}

variable "curation_lambda_memory_mb" {
  type        = number
  default     = 512
  description = "Curation Lambda memory size (MB)"
}
