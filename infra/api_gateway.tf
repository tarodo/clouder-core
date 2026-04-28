resource "aws_apigatewayv2_api" "collector" {
  name          = local.api_name
  protocol_type = "HTTP"

  dynamic "cors_configuration" {
    for_each = length(var.cors_allowed_origins) > 0 ? [1] : []
    content {
      allow_origins     = var.cors_allowed_origins
      allow_methods     = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
      allow_headers     = ["authorization", "content-type", "x-correlation-id"]
      expose_headers    = ["x-correlation-id"]
      max_age           = 600
      allow_credentials = false
    }
  }
}

resource "aws_apigatewayv2_integration" "collector_lambda" {
  api_id                 = aws_apigatewayv2_api.collector.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.collector.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "collect_bp_releases" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "POST /collect_bp_releases"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "get_run" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /runs/{run_id}"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "list_tracks" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /tracks"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "list_artists" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /artists"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "list_albums" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /albums"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "list_labels" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /labels"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "list_styles" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /styles"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "spotify_not_found" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /tracks/spotify-not-found"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.collector.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "allow_apigw" {
  statement_id  = "AllowExecutionFromApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.collector.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.collector.execution_arn}/*/*"
}
