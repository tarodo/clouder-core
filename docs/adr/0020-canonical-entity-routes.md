# ADR-0020: Canonical top-level routes for artist/label detail pages
Status: Accepted
Date: 2026-06-04

## Context

Artist and label detail pages were reachable only through style-scoped routes
(`/library/:styleId/artists/:artistId`, `/library/:styleId/labels/:labelId`). The
`styleId` was used only for the URL guard and the "← Back to {style}" link — the data
fetch ignores it (`GET /artists/{id}` and `GET /labels/{id}` take no style). Because
the route required a `styleId`, any context with no single style — the playlist player
panel above all — could not build the URL, so artist/label names rendered as plain
text instead of links.

## Decision

Move the detail pages to top-level canonical routes: `/artists/:artistId` and
`/labels/:labelId`. Any context now links to them unconditionally, and the conditional
`styleId` link plumbing (the optional `styleId` prop on `ArtistTile`/`LabelTile`)
disappears. Back navigation uses browser history (`navigate(-1)`) with a `/library`
fallback for deep links / new tabs. Library **list** pages stay style-scoped
(`/library/:styleId`, `/library/:styleId/artists`) — an intentional browse-by-style
surface whose list endpoints filter by `?style=`. Frontend-only: no backend, API, DB,
or OpenAPI change (the id-only endpoints already exist).

## Consequences

- Clean URL split: `/library/...` is browse-by-style, `/artists` & `/labels` are
  entity pages. No collision with `:styleId`.
- Old style-scoped detail URLs are removed; an external bookmark to
  `/library/:styleId/artists/:id` breaks. Acceptable — internal app only.
- Relates to ADR-0009 (frontend stack / routing).

**Cross-references:** `../frontend/features.md`. Source spec (now archived):
`../archive/specs/2026-06-02-decouple-artist-label-from-style-design.md`.
