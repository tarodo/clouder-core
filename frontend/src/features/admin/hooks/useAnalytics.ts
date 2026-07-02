import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface AdminUser {
  id: string;
  display_name: string | null;
}

export type UsersResponse = { users: AdminUser[]; correlation_id?: string };

export function useUsers() {
  return useQuery({
    queryKey: ['admin', 'users'],
    queryFn: () => api<UsersResponse>('/admin/users'),
    staleTime: 300_000,
  });
}

// Athena returns all columns as strings; nullable columns arrive as null.
export interface UserDailyRow {
  user_id: string;
  activity_type: string;
  dt: string;
  sessions: string | number;
  avg_tracks_listened: string | number | null;
  avg_tracks_promoted: string | number | null;
  avg_tracks_deleted: string | number | null;
  p50_duration_ms: string | number | null;
  p90_duration_ms: string | number | null;
  p50_time_per_track_ms: string | number | null;
  p90_time_per_track_ms: string | number | null;
}

export interface SessionRow {
  user_id: string;
  activity_type: string;
  dt: string;
  session_seq: string | number | null;
  ts_start: string | null;
  ts_end: string | null;
  duration_ms: string | number | null;
  tracks_listened: string | number | null;
  tracks_promoted: string | number | null;
  tracks_deleted: string | number | null;
}

export type UserDailyResponse = { 'user-daily': UserDailyRow[]; correlation_id?: string };
export type SessionsResponse = { sessions: SessionRow[]; correlation_id?: string };

export interface AnalyticsRange {
  from: string;
  to: string;
}

export function useUserDaily(userId: string, range: AnalyticsRange) {
  return useQuery({
    queryKey: ['admin', 'analytics', 'user-daily', userId, range.from, range.to],
    queryFn: () =>
      api<UserDailyResponse>(
        `/v1/analytics/user-daily?user_id=${encodeURIComponent(userId)}&from=${range.from}&to=${range.to}`,
      ),
    enabled: userId.trim().length > 0,
    staleTime: 60_000,
  });
}

export function useSessions(userId: string, range: AnalyticsRange) {
  return useQuery({
    queryKey: ['admin', 'analytics', 'sessions', userId, range.from, range.to],
    queryFn: () =>
      api<SessionsResponse>(
        `/v1/analytics/sessions?user_id=${encodeURIComponent(userId)}&from=${range.from}&to=${range.to}`,
      ),
    enabled: userId.trim().length > 0,
    staleTime: 60_000,
  });
}
