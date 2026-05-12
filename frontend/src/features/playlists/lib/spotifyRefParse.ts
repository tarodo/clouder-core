export class InvalidSpotifyRefError extends Error {
  constructor(message = 'invalid_spotify_ref') {
    super(message);
    this.name = 'InvalidSpotifyRefError';
  }
}

const BASE62 = /^[0-9A-Za-z]{22}$/;
const URI_RE = /^spotify:track:([0-9A-Za-z]{22})$/;
const URL_RE = /^https?:\/\/open\.spotify\.com\/track\/([0-9A-Za-z]{22})(?:\?.*)?$/;

export function parseSpotifyRef(input: string): string {
  const ref = (input ?? '').trim();
  if (!ref) throw new InvalidSpotifyRefError();

  const uriMatch = URI_RE.exec(ref);
  if (uriMatch && uriMatch[1]) return uriMatch[1];

  const urlMatch = URL_RE.exec(ref);
  if (urlMatch && urlMatch[1]) return urlMatch[1];

  if (BASE62.test(ref)) return ref;

  throw new InvalidSpotifyRefError();
}
