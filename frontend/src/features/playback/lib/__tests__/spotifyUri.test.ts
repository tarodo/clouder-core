import { describe, it, expect } from 'vitest';
import { toSpotifyUri } from '../spotifyUri';

describe('toSpotifyUri', () => {
  it('builds spotify:track:<id>', () => {
    expect(toSpotifyUri('abc123')).toBe('spotify:track:abc123');
  });
  it('returns null for null id', () => {
    expect(toSpotifyUri(null)).toBeNull();
  });
});
