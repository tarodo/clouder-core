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

export interface AdminUser {
  id: string;
  display_name: string | null;
}

export function useUsers() {
  return useQuery({
    queryKey: ['admin', 'users'],
    queryFn: () => api<{ users: AdminUser[] }>('/admin/users'),
    staleTime: 300_000,
  });
}

/** Browser UTC offset in minutes, east-positive (UTC+4 → 240). Backend buckets local days by it. */
export function tzOffsetMin(): number {
  return -new Date().getTimezoneOffset();
}

/** Empty userId → backend defaults to the calling admin. */
function query(userId: string): string {
  const off = tzOffsetMin();
  return userId
    ? `tz_offset_min=${off}&user_id=${encodeURIComponent(userId)}`
    : `tz_offset_min=${off}`;
}

export function useListening(userId = '') {
  const qs = query(userId);
  return useQuery({
    queryKey: ['admin', 'analytics', 'listening', qs],
    queryFn: () => api<ListeningResponse>(`/v1/analytics/listening?${qs}`),
    staleTime: 60_000,
  });
}

export function useFunnel(userId = '') {
  const qs = query(userId);
  return useQuery({
    queryKey: ['admin', 'analytics', 'funnel', qs],
    queryFn: () => api<FunnelResponse>(`/admin/analytics/funnel?${qs}`),
    staleTime: 60_000,
  });
}
