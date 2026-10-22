import { describe, expect, it } from 'vitest';
import { formatYoutubeStats } from '../youtubeStats';

describe('formatYoutubeStats', () => {
  it('renders found and not-found always', () => {
    expect(
      formatYoutubeStats({
        week_number: 1, total: 20, found: 18, review: 0, not_found: 2, pending: 0,
      }),
    ).toBe('YouTube: 18/20 found · 2 not found');
  });

  it('appends review and pending only when non-zero', () => {
    expect(
      formatYoutubeStats({
        week_number: 1, total: 20, found: 15, review: 2, not_found: 1, pending: 2,
      }),
    ).toBe('YouTube: 15/20 found · 2 review · 1 not found · 2 pending');
  });
});
