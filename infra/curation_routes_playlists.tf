# ── curation Lambda playlist routes (spec 2026-05-11) ────────────────
# Append-only: reuses the curation Lambda integration + JWT authorizer
# defined in curation.tf.

locals {
  curation_playlist_routes = [
    "POST /playlists",
    "GET /playlists",
    "GET /playlists/{id}",
    "PATCH /playlists/{id}",
    "DELETE /playlists/{id}",
    "GET /playlists/{id}/tracks",
    "POST /playlists/{id}/tracks",
    "DELETE /playlists/{id}/tracks/{track_id}",
    "POST /playlists/{id}/tracks/order",
    "POST /playlists/{id}/cover/upload-url",
    "POST /playlists/{id}/cover/confirm",
    "DELETE /playlists/{id}/cover",
    "POST /playlists/{id}/tracks/import-spotify",
    "POST /playlists/{id}/publish",
    "GET /playlists/{id}/tracks/{track_id}/match-candidates",
    "POST /playlists/{id}/tracks/{track_id}/match-resolve",
  ]
}

resource "aws_apigatewayv2_route" "curation_playlists" {
  for_each = toset(local.curation_playlist_routes)

  api_id    = aws_apigatewayv2_api.collector.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.curation.id}"

  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
