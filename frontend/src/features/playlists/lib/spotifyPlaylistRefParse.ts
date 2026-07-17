import { InvalidSpotifyRefError } from './spotifyRefParse';

const BASE62 = /^[0-9A-Za-z]{22}$/;
const URI_RE = /^spotify:playlist:([0-9A-Za-z]{22})$/;
const URL_RE = /^https?:\/\/open\.spotify\.com\/playlist\/([0-9A-Za-z]{22})(?:\?.*)?$/;

export function parseSpotifyPlaylistRef(input: string): string {
  const ref = (input ?? '').trim();
  if (!ref) throw new InvalidSpotifyRefError();

  const uriMatch = URI_RE.exec(ref);
  if (uriMatch && uriMatch[1]) return uriMatch[1];

  const urlMatch = URL_RE.exec(ref);
  if (urlMatch && urlMatch[1]) return urlMatch[1];

  if (BASE62.test(ref)) return ref;

  throw new InvalidSpotifyRefError();
}
