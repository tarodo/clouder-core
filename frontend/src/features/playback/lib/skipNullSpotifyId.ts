export interface PlayableTrack {
  spotify_id: string | null;
}

export function findNextPlayable<T extends PlayableTrack>(
  tracks: readonly T[],
  startIndex: number,
  direction: 1 | -1,
): number | null {
  if (tracks.length === 0) return null;
  if (startIndex < 0 || startIndex >= tracks.length) return null;
  let i = startIndex;
  while (i >= 0 && i < tracks.length) {
    const track = tracks[i];
    if (track && track.spotify_id != null && track.spotify_id !== '') return i;
    i += direction;
  }
  return null;
}
