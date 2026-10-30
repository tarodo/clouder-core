import { describe, expect, it } from 'vitest';
import { formatAnalysisStats } from '../analysisStats';

describe('formatAnalysisStats', () => {
  it('renders the AI check and the profile against the matched tracks', () => {
    expect(
      formatAnalysisStats({ week_number: 41, total: 1678, checked: 1678, ai: 171, profiled: 1428 }),
    ).toEqual(['AI: 1678/1678 checked · 171 AI', 'Profile: 1428/1678 profiled']);
  });

  it('keeps zeros visible: nothing checked yet is news', () => {
    expect(
      formatAnalysisStats({ week_number: 41, total: 335, checked: 0, ai: 0, profiled: 0 }),
    ).toEqual(['AI: 0/335 checked · 0 AI', 'Profile: 0/335 profiled']);
  });
});
