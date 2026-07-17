import { describe, it, expect } from 'vitest';
import { parseSpotifyPlaylistRef } from '../spotifyPlaylistRefParse';
import { InvalidSpotifyRefError } from '../spotifyRefParse';

describe('parseSpotifyPlaylistRef', () => {
  it('parses uri form', () => {
    expect(parseSpotifyPlaylistRef('spotify:playlist:37i9dQZF1DXcBWIGoYBM5M')).toBe(
      '37i9dQZF1DXcBWIGoYBM5M',
    );
  });
  it('parses url form with query', () => {
    expect(
      parseSpotifyPlaylistRef('https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=x'),
    ).toBe('37i9dQZF1DXcBWIGoYBM5M');
  });
  it('parses bare id', () => {
    expect(parseSpotifyPlaylistRef('37i9dQZF1DXcBWIGoYBM5M')).toBe('37i9dQZF1DXcBWIGoYBM5M');
  });
  it('rejects a track ref', () => {
    expect(() => parseSpotifyPlaylistRef('spotify:track:5xkAVrKKnHeBHb1Mqt6wEt')).toThrow(
      InvalidSpotifyRefError,
    );
  });
});
