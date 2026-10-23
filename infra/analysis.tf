# ── Audio analysis: the external analyzer (clouder-analyzer) and the admin view ──
# The service routes get their own authorizer resource: API Gateway caches an
# authorizer's verdict per Authorization header across all of its routes, so a
# shared one would let a cached service-token "allow" reach user routes. The
# same Lambda serves both and branches on routeKey (collector/auth_authorizer.py).

resource "aws_apigatewayv2_authorizer" "analysis_service" {
  api_id                            = aws_apigatewayv2_api.collector.id
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = aws_lambda_alias.live["auth_authorizer"].invoke_arn
  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
  identity_sources                  = ["$request.header.Authorization"]
  authorizer_result_ttl_in_seconds  = var.auth_authorizer_cache_ttl_seconds
  name                              = "${local.name_prefix}-analysis-authorizer"

  depends_on = [aws_lambda_permission.api_live]
}

resource "aws_apigatewayv2_route" "analysis_claim" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "POST /v1/analysis/claim"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.analysis_service.id
}

resource "aws_apigatewayv2_route" "analysis_results" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "POST /v1/analysis/results"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.analysis_service.id
}

resource "aws_apigatewayv2_route" "analysis_features" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "POST /v1/analysis/features"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.analysis_service.id
}

resource "aws_apigatewayv2_route" "admin_analysis_status" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /admin/analysis/status"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "admin_analysis_requeue" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "POST /admin/analysis/requeue"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
