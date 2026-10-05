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

/** Empty userId → the caller's own data; only admins may pass another user. */
function query(userId: string): string {
  const off = tzOffsetMin();
  return userId
    ? `tz_offset_min=${off}&user_id=${encodeURIComponent(userId)}`
    : `tz_offset_min=${off}`;
}

export function useListening(userId = '') {
  const qs = query(userId);
  return useQuery({
    queryKey: ['analytics', 'listening', qs],
    queryFn: () => api<ListeningResponse>(`/v1/analytics/listening?${qs}`),
    staleTime: 60_000,
  });
}

export function useFunnel(userId = '') {
  const qs = query(userId);
  return useQuery({
    queryKey: ['analytics', 'funnel', qs],
    queryFn: () => api<FunnelResponse>(`/v1/analytics/funnel?${qs}`),
    staleTime: 60_000,
  });
}
