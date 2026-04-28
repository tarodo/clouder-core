# ── curation Lambda triage routes (spec-D: triage blocks) ──────────
# Append-only: reuses the curation Lambda integration + JWT authorizer
# defined in curation.tf. Mirrors the spec-C category routes pattern.

locals {
  curation_triage_routes = [
    "POST /triage/blocks",
    "GET /styles/{style_id}/triage/blocks",
    "GET /triage/blocks",
    "GET /triage/blocks/{id}",
    "GET /triage/blocks/{id}/buckets/{bucket_id}/tracks",
    "POST /triage/blocks/{id}/move",
    "POST /triage/blocks/{src_id}/transfer",
    "POST /triage/blocks/{id}/finalize",
    "DELETE /triage/blocks/{id}",
  ]
}

resource "aws_apigatewayv2_route" "curation_triage" {
  for_each = toset(local.curation_triage_routes)

  api_id    = aws_apigatewayv2_api.collector.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.curation.id}"

  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
