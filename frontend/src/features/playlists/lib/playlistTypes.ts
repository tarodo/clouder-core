// frontend/src/features/playlists/lib/playlistTypes.ts

export type PlaylistTrackOrigin = 'beatport' | 'spotify_user_import';

export type PlaylistStatus = 'active' | 'completed';

export interface Playlist {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  is_public: boolean;
  cover_s3_key: string | null;
  cover_url: string | null;
  cover_uploaded_at: string | null;
  spotify_playlist_id: string | null;
  last_published_at: string | null;
  needs_republish: boolean;
  track_count: number;
  status: PlaylistStatus;
  created_at: string;
  updated_at: string;
}

export interface PlaylistTrackArtist { id: string; name: string }
export interface PlaylistTrackLabel { id: string; name: string }
export interface PlaylistTrackTag { id: string; name: string; color: string | null }

export interface PlaylistTrack {
  track_id: string;
  position: number;
  added_at: string;
  title: string;
  spotify_id: string | null;
  isrc: string | null;
  length_ms: number | null;
  origin: PlaylistTrackOrigin;
  mix_name: string | null;
  artists: PlaylistTrackArtist[];
  label: PlaylistTrackLabel | null;
  bpm: number | null;
  spotify_release_date: string | null;
  is_ai_suspected: boolean;
  tags: PlaylistTrackTag[];
}

export interface PaginatedPlaylists {
  items: Playlist[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

export interface PaginatedPlaylistTracks {
  items: PlaylistTrack[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

export interface AddTracksResult {
  added: string[];
  skipped_duplicates: string[];
  position_after: number;
  correlation_id?: string;
}

export interface ImportSpotifyResult {
  added: { track_id: string; spotify_id: string; title: string }[];
  skipped: { ref: string; reason: 'invalid_ref' | 'not_found' | 'already_in_playlist' }[];
  position_after: number;
  correlation_id?: string;
}

export interface PublishResult {
  spotify_playlist_id: string;
  spotify_url: string;
  skipped_tracks: { track_id: string; title: string; reason: string }[];
  cover_failed: boolean;
  published_at: string;
  correlation_id?: string;
}

export interface CoverUploadUrlResponse {
  upload_url: string;
  s3_key: string;
  expires_in: number;
  correlation_id?: string;
}
