import { describe, it, expect } from 'vitest';
import type { PlaylistTrack } from '../playlistTypes';
import { beatportTrackUrl, buildPlaylistExport } from '../playlistExport';

function track(overrides: Partial<PlaylistTrack> = {}): PlaylistTrack {
  return {
    track_id: 't1',
    position: 0,
    added_at: '2026-01-01T00:00:00Z',
    title: 'Strobe',
    spotify_id: 'sp1',
    isrc: 'US1234567890',
    length_ms: 600000,
    origin: 'beatport',
    mix_name: 'Extended Mix',
    artists: [{ id: 'a1', name: 'deadmau5' }],
    label: { id: 'l1', name: 'mau5trap' },
    bpm: 128,
    spotify_release_date: null,
    is_ai_suspected: false,
    tags: [],
    ytmusic: { status: 'matched', url: 'https://music.youtube.com/watch?v=yt1', confidence: 0.9 },
    beatport_track_id: '123456',
    beatport_slug: 'strobe',
    ...overrides,
  };
}

describe('beatportTrackUrl', () => {
  it('builds a slugged URL when id and slug are present', () => {
    expect(beatportTrackUrl('123456', 'strobe')).toBe(
      'https://www.beatport.com/track/strobe/123456',
    );
  });

  it('uses a placeholder slug when slug is missing', () => {
    expect(beatportTrackUrl('123456', null)).toBe('https://www.beatport.com/track/_/123456');
    expect(beatportTrackUrl('123456', '   ')).toBe('https://www.beatport.com/track/_/123456');
  });

  it('returns null when id is missing', () => {
    expect(beatportTrackUrl(null, 'strobe')).toBeNull();
    expect(beatportTrackUrl(undefined, undefined)).toBeNull();
  });
});

describe('buildPlaylistExport', () => {
  it('wraps tracks with playlist name and count', () => {
    const out = buildPlaylistExport('My set', [track(), track({ track_id: 't2' })]);
    expect(out.playlist).toBe('My set');
    expect(out.track_count).toBe(2);
    expect(out.tracks).toHaveLength(2);
  });

  it('maps all fields for a complete track', () => {
    const [t] = buildPlaylistExport('My set', [track()]).tracks;
    expect(t).toEqual({
      title: 'Strobe',
      mix_name: 'Extended Mix',
      artists: ['deadmau5'],
      label: 'mau5trap',
      isrc: 'US1234567890',
      beatport_url: 'https://www.beatport.com/track/strobe/123456',
      spotify_url: 'https://open.spotify.com/track/sp1',
      youtube_music_url: 'https://music.youtube.com/watch?v=yt1',
    });
  });

  it('emits nulls for missing data and joins multiple artists', () => {
    const [t] = buildPlaylistExport('My set', [
      track({
        mix_name: null,
        isrc: null,
        label: null,
        spotify_id: null,
        ytmusic: null,
        beatport_track_id: null,
        beatport_slug: null,
        artists: [
          { id: 'a1', name: 'A' },
          { id: 'a2', name: 'B' },
        ],
      }),
    ]).tracks;
    expect(t.artists).toEqual(['A', 'B']);
    expect(t.mix_name).toBeNull();
    expect(t.label).toBeNull();
    expect(t.isrc).toBeNull();
    expect(t.beatport_url).toBeNull();
    expect(t.spotify_url).toBeNull();
    expect(t.youtube_music_url).toBeNull();
  });

  it('omits the YouTube URL when the match is not "matched"', () => {
    const [t] = buildPlaylistExport('My set', [
      track({ ytmusic: { status: 'needs_review', url: null } }),
    ]).tracks;
    expect(t.youtube_music_url).toBeNull();
  });

  it('emits null YouTube URL when matched but url is missing', () => {
    const [t] = buildPlaylistExport('My set', [
      track({ ytmusic: { status: 'matched', url: null } }),
    ]).tracks;
    expect(t.youtube_music_url).toBeNull();
  });
});
