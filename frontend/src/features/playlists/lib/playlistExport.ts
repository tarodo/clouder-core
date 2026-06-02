// frontend/src/features/playlists/lib/playlistExport.ts
import type { PlaylistTrack } from './playlistTypes';

export interface PlaylistExportTrack {
  title: string;
  mix_name: string | null;
  artists: string[];
  label: string | null;
  isrc: string | null;
  beatport_url: string | null;
  spotify_url: string | null;
  youtube_music_url: string | null;
}

export interface PlaylistExport {
  playlist: string;
  track_count: number;
  tracks: PlaylistExportTrack[];
}

/**
 * Build a beatport.com track URL. The slug is not always stored; when missing
 * we use the `_` placeholder — Beatport redirects to the canonical URL by id.
 * Returns null when there is no Beatport id (e.g. non-Beatport-origin tracks).
 */
export function beatportTrackUrl(
  id: string | null | undefined,
  slug: string | null | undefined,
): string | null {
  if (!id) return null;
  const s = slug && slug.trim() ? slug.trim() : '_';
  return `https://www.beatport.com/track/${s}/${id}`;
}

export function buildPlaylistExport(
  playlistName: string,
  tracks: PlaylistTrack[],
): PlaylistExport {
  return {
    playlist: playlistName,
    track_count: tracks.length,
    tracks: tracks.map((t) => ({
      title: t.title,
      mix_name: t.mix_name,
      artists: t.artists.map((a) => a.name),
      label: t.label?.name ?? null,
      isrc: t.isrc,
      beatport_url: beatportTrackUrl(t.beatport_track_id, t.beatport_slug),
      spotify_url: t.spotify_id ? `https://open.spotify.com/track/${t.spotify_id}` : null,
      youtube_music_url:
        t.ytmusic?.status === 'matched' ? (t.ytmusic.url ?? null) : null,
    })),
  };
}
