# Non-secret production values. Every terraform plan and apply reads this file: the
# pull-request plan and both deploy phases (ADR-0028). Secrets and environment URLs
# arrive as TF_VAR_* from GitHub (docs/ops/deploy.md).
environment                         = "prod"
canonicalization_enabled            = true
silver_events_table                 = "clouder_silver.events"
gemini_api_key_ssm_parameter        = "/clouder/gemini/api_key"
openai_api_key_ssm_parameter        = "/clouder/openai/api_key"
tavily_api_key_ssm_parameter        = "/clouder/tavily/api_key"
deepseek_api_key_ssm_parameter      = "/clouder/deepseek/api_key"
spotify_search_enabled              = true
vendor_match_enabled                = true
spotify_client_id_ssm_parameter     = "/clouder/spotify/client_id"
spotify_client_secret_ssm_parameter = "/clouder/spotify/client_secret"
ytmusic_client_id_ssm_parameter     = "/clouder/ytmusic/client_id"
ytmusic_client_secret_ssm_parameter = "/clouder/ytmusic/client_secret"
youtube_api_key_ssm_parameter       = "/clouder/youtube/api_key"
migration_aurora_auth_mode          = "iam"
enable_secretsmanager_vpc_endpoint  = false
