export function toSpotifyUri(spotifyId: string | null): string | null {
  if (spotifyId == null || spotifyId === '') return null;
  return `spotify:track:${spotifyId}`;
}
