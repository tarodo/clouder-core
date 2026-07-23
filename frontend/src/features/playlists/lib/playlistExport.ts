// frontend/src/features/playlists/lib/playlistExport.ts
//
// Shape of GET /playlists/{id}/export. The payload used to be assembled here
// from the loaded tracks; it moved server-side when it grew to carry the merged
// enrichment blob for every artist and label — building it here would cost an
// /artists/{id} or /labels/{id} request per entity.

export interface PlaylistExportComment {
  author: string;
  text: string;
  like_count: number;
  published_at: string | null;
}

export interface PlaylistExportTrack {
  title: string;
  mix_name: string | null;
  artists: string[];
  label: string | null;
  isrc: string | null;
  beatport_url: string | null;
  spotify_url: string | null;
  youtube_music_url: string | null;
  comments: PlaylistExportComment[];
}

/** An artist or label appearing in the playlist, described once. */
export interface PlaylistExportEntity {
  id: string;
  name: string;
  /** Merged enrichment blob; null when the entity has not been enriched. */
  info: Record<string, unknown> | null;
}

export interface PlaylistExport {
  playlist: string;
  track_count: number;
  tracks: PlaylistExportTrack[];
  artists: PlaylistExportEntity[];
  labels: PlaylistExportEntity[];
  correlation_id?: string;
}

/**
 * Build a beatport.com track URL. The slug is not always stored; when missing
 * we use the `_` placeholder — Beatport redirects to the canonical URL by id.
 * Returns null when there is no Beatport id (e.g. non-Beatport-origin tracks).
 *
 * Still used by the track row; the export gets this URL from the API now.
 */
export function beatportTrackUrl(
  id: string | null | undefined,
  slug: string | null | undefined,
): string | null {
  if (!id) return null;
  const s = slug && slug.trim() ? slug.trim() : '_';
  return `https://www.beatport.com/track/${s}/${id}`;
}
