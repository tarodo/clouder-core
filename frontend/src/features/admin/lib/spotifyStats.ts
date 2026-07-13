import type { SpotifyWeekStats } from '../hooks/useCoverage';

export function formatSpotifyStats(s: SpotifyWeekStats): string {
  const parts = [
    `Spotify: ${s.found}/${s.total} found`,
    `${s.not_found} not found`,
  ];
  if (s.pending > 0) parts.push(`${s.pending} pending`);
  if (s.no_isrc > 0) parts.push(`${s.no_isrc} no ISRC`);
  return parts.join(' · ');
}
