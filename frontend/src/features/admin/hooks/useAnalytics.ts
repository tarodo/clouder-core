import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface ListeningTotal {
  listened_ms: number;
  tracks: number;
}

export interface ListeningDay extends ListeningTotal {
  dt: string;
}

export interface ListeningResponse {
  today: string;
  totals: { day: ListeningTotal; week: ListeningTotal; month: ListeningTotal };
  daily: ListeningDay[];
}

export type FunnelStageName = 'triaged' | 'categorized' | 'playlisted';

export interface FunnelStage {
  stage: FunnelStageName;
  day: number;
  week: number;
  month: number;
}

export interface FunnelResponse {
  today: string;
  stages: FunnelStage[];
}

/** Browser UTC offset in minutes, east-positive (UTC+4 → 240). Backend buckets local days by it. */
export function tzOffsetMin(): number {
  return -new Date().getTimezoneOffset();
}

export function useListening() {
  const off = tzOffsetMin();
  return useQuery({
    queryKey: ['admin', 'analytics', 'listening', off],
    queryFn: () => api<ListeningResponse>(`/v1/analytics/listening?tz_offset_min=${off}`),
    staleTime: 60_000,
  });
}

export function useFunnel() {
  const off = tzOffsetMin();
  return useQuery({
    queryKey: ['admin', 'analytics', 'funnel', off],
    queryFn: () => api<FunnelResponse>(`/admin/analytics/funnel?tz_offset_min=${off}`),
    staleTime: 60_000,
  });
}
