# ── curation Lambda track-tags routes (spec 2026-05-11) ────────────
# Append-only: reuses the curation Lambda integration + JWT authorizer
# defined in curation.tf. Mirrors the triage append pattern.

locals {
  curation_tags_routes = [
    "POST /tags",
    "GET /tags",
    "PATCH /tags/{tag_id}",
    "DELETE /tags/{tag_id}",
    "GET /tracks/{track_id}/tags",
    "PUT /tracks/{track_id}/tags",
    "POST /tracks/{track_id}/tags",
    "DELETE /tracks/{track_id}/tags/{tag_id}",
  ]
}

resource "aws_apigatewayv2_route" "curation_tags" {
  for_each = toset(local.curation_tags_routes)

  api_id    = aws_apigatewayv2_api.collector.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.curation.id}"

  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
