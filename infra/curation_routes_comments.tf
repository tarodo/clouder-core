# ── curation Lambda track-comments route ───────────────────────────
# Append-only: reuses the curation Lambda integration + JWT authorizer.

locals {
  curation_comments_routes = [
    "GET /tracks/{track_id}/comments",
    "GET /playlists/{id}/comments",
  ]
}

resource "aws_apigatewayv2_route" "curation_comments" {
  for_each = toset(local.curation_comments_routes)

  api_id    = aws_apigatewayv2_api.collector.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.curation.id}"

  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
