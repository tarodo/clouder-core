import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { paths } from '../../../api/schema';

export type AnalyticsResult =
  paths['/v1/analytics/triage']['get']['responses'][200]['content']['application/json'];

export type DashboardName = 'triage' | 'taste' | 'funnel' | 'playback' | 'ops';

export interface AnalyticsRange {
  from: string;
  to: string;
}

export function useAnalytics(name: DashboardName, range: AnalyticsRange) {
  return useQuery({
    queryKey: ['admin', 'analytics', name, range.from, range.to],
    queryFn: () =>
      api<AnalyticsResult>(
        `/v1/analytics/${name}?from=${range.from}&to=${range.to}`,
      ),
    staleTime: 60_000,
  });
}
