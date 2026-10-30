import type { AnalysisWeekStats } from '../hooks/useCoverage';

/** Two tooltip lines over the week's matched tracks: the AI check and the audio profile. */
export function formatAnalysisStats(s: AnalysisWeekStats): string[] {
  return [
    `AI: ${s.checked}/${s.total} checked · ${s.ai} AI`,
    `Profile: ${s.profiled}/${s.total} profiled`,
  ];
}
