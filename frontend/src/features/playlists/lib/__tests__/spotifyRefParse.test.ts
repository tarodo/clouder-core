import { describe, it, expect } from 'vitest';
import { parseSpotifyRef, InvalidSpotifyRefError } from '../spotifyRefParse';

describe('parseSpotifyRef', () => {
  it('parses spotify:track URI', () => {
    expect(parseSpotifyRef('spotify:track:5PB5CTjuKcD2GUlIMtU1gr')).toBe('5PB5CTjuKcD2GUlIMtU1gr');
  });
  it('parses open.spotify.com URL', () => {
    expect(parseSpotifyRef('https://open.spotify.com/track/5PB5CTjuKcD2GUlIMtU1gr')).toBe(
      '5PB5CTjuKcD2GUlIMtU1gr',
    );
  });
  it('parses URL with query string', () => {
    expect(
      parseSpotifyRef('https://open.spotify.com/track/5PB5CTjuKcD2GUlIMtU1gr?si=foo'),
    ).toBe('5PB5CTjuKcD2GUlIMtU1gr');
  });
  it('parses bare 22-char base62 id', () => {
    expect(parseSpotifyRef('5PB5CTjuKcD2GUlIMtU1gr')).toBe('5PB5CTjuKcD2GUlIMtU1gr');
  });
  it('trims whitespace', () => {
    expect(parseSpotifyRef('  5PB5CTjuKcD2GUlIMtU1gr  ')).toBe('5PB5CTjuKcD2GUlIMtU1gr');
  });
  it('rejects empty string', () => {
    expect(() => parseSpotifyRef('')).toThrow(InvalidSpotifyRefError);
  });
  it('rejects playlist URL', () => {
    expect(() =>
      parseSpotifyRef('https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M'),
    ).toThrow(InvalidSpotifyRefError);
  });
  it('rejects too-short id', () => {
    expect(() => parseSpotifyRef('abc')).toThrow(InvalidSpotifyRefError);
  });
  it('rejects non-base62 id', () => {
    expect(() => parseSpotifyRef('5PB5CTjuKcD2GUlIMtU1g!')).toThrow(InvalidSpotifyRefError);
  });
  it('rejects album URI', () => {
    expect(() => parseSpotifyRef('spotify:album:5PB5CTjuKcD2GUlIMtU1gr')).toThrow(
      InvalidSpotifyRefError,
    );
  });
});
