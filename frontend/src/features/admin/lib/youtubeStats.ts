import type { YoutubeWeekStats } from '../hooks/useCoverage';

export function formatYoutubeStats(s: YoutubeWeekStats): string {
  const parts = [`YouTube: ${s.found}/${s.total} found`];
  if (s.review > 0) parts.push(`${s.review} review`);
  parts.push(`${s.not_found} not found`);
  if (s.pending > 0) parts.push(`${s.pending} pending`);
  return parts.join(' · ');
}
