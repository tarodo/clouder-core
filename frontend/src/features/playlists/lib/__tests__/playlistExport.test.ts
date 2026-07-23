import { describe, it, expect } from 'vitest';
import { beatportTrackUrl } from '../playlistExport';

// The export payload itself is assembled server-side (GET /playlists/{id}/export)
// and covered by tests/unit/test_playlist_export.py; only the URL helper — still
// used by the track row — lives here.

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
