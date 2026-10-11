# ── `live` aliases for the API functions (ADR-0029) ──
# API Gateway calls the alias, so a failed smoke test can point it back to the previous
# version in seconds (scripts/api_aliases.py). Workers stay unqualified: SQS retries
# and DLQs already absorb a bad worker deploy.

locals {
  api_functions = {
    collector       = aws_lambda_function.collector
    curation        = aws_lambda_function.curation
    auth_handler    = aws_lambda_function.auth_handler
    auth_authorizer = aws_lambda_function.auth_authorizer
    analytics       = aws_lambda_function.analytics
    telemetry       = aws_lambda_function.telemetry
  }
}

resource "aws_lambda_alias" "live" {
  for_each         = local.api_functions
  name             = "live"
  function_name    = each.value.function_name
  function_version = each.value.version
}

# Alias-scoped invoke permissions. The unqualified ones stay so nothing breaks while an
# integration switches; integrations depend on these.
resource "aws_lambda_permission" "api_live" {
  for_each      = local.api_functions
  statement_id  = "AllowAPIGatewayInvokeLive"
  action        = "lambda:InvokeFunction"
  function_name = each.value.function_name
  qualifier     = aws_lambda_alias.live[each.key].name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.collector.execution_arn}/*/*"
}

output "api_alias_functions" {
  description = "API functions behind the live alias (scripts/api_aliases.py)"
  value       = [for f in local.api_functions : f.function_name]
}
