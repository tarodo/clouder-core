import { describe, expect, it } from 'vitest';
import { formatSpotifyStats } from '../spotifyStats';

describe('formatSpotifyStats', () => {
  it('renders found and not-found always', () => {
    expect(
      formatSpotifyStats({
        week_number: 1, total: 50, found: 45, not_found: 5,
        pending: 0, no_isrc: 0,
      }),
    ).toBe('Spotify: 45/50 found · 5 not found');
  });

  it('appends pending and no-ISRC only when non-zero', () => {
    expect(
      formatSpotifyStats({
        week_number: 1, total: 50, found: 45, not_found: 3,
        pending: 1, no_isrc: 1,
      }),
    ).toBe('Spotify: 45/50 found · 3 not found · 1 pending · 1 no ISRC');
  });
});
