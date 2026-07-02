import { Alert, Loader, Stack, Table, Text } from '@mantine/core';
import { LineChart } from '@mantine/charts';
import { useTranslation } from 'react-i18next';
import {
  useUserDaily,
  useSessions,
  type UserDailyRow,
  type SessionRow,
  type AnalyticsRange,
} from '../hooks/useAnalytics';

// Coerce Athena string-or-null numeric to display string.
// NULL/undefined/NaN → em-dash. Numbers formatted per fmtMs or plain.
function n(val: string | number | null | undefined): string {
  if (val === null || val === undefined) return '—';
  const v = Number(val);
  return Number.isNaN(v) ? '—' : String(v);
}

// Format milliseconds as m:ss (e.g. 120000 → "2:00").
function fmtMs(val: string | number | null | undefined): string {
  if (val === null || val === undefined) return '—';
  const ms = Number(val);
  if (Number.isNaN(ms)) return '—';
  const totalSec = Math.round(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function UserDailyTable({ userId, range }: { userId: string; range: AnalyticsRange }) {
  const { t } = useTranslation();
  const q = useUserDaily(userId, range);
  const rows: UserDailyRow[] = q.data?.['user-daily'] ?? [];

  if (q.isLoading) return <Loader size="sm" data-testid="loader" />;
  if (q.isError) return <Alert color="red" role="alert">{t('admin.analytics.load_failed')}</Alert>;
  if (rows.length === 0) return <Text c="dimmed">{t('admin.analytics.empty')}</Text>;

  // Optional line chart: sessions per day (one line per activity_type).
  // ponytail: simple flat series — one point per row; if multiple activity_types share a dt
  // they each get their own series entry. Good enough for the MVP.
  const chartData = rows.map((r) => ({
    dt: r.dt,
    [r.activity_type]: Number(r.sessions),
  }));
  const activities = [...new Set(rows.map((r) => r.activity_type))];
  const series = activities.map((a, i) => ({
    name: a,
    color: ['indigo.6', 'teal.6', 'grape.6'][i % 3],
  }));

  return (
    <Stack gap="sm">
      {rows.length > 0 && (
        <LineChart
          h={180}
          data={chartData}
          dataKey="dt"
          series={series}
          withLegend
        />
      )}
      <Table striped withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('admin.analytics.col.date')}</Table.Th>
            <Table.Th>{t('admin.analytics.col.activity')}</Table.Th>
            <Table.Th>{t('admin.analytics.col.sessions')}</Table.Th>
            <Table.Th>{t('admin.analytics.col.avg_listened')}</Table.Th>
            <Table.Th>{t('admin.analytics.col.avg_promoted')}</Table.Th>
            <Table.Th>{t('admin.analytics.col.avg_deleted')}</Table.Th>
            <Table.Th>{t('admin.analytics.col.p50_duration')}</Table.Th>
            <Table.Th>{t('admin.analytics.col.p90_duration')}</Table.Th>
            <Table.Th>{t('admin.analytics.col.p50_tpt')}</Table.Th>
            <Table.Th>{t('admin.analytics.col.p90_tpt')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((r, i) => (
            <Table.Tr key={i}>
              <Table.Td>{r.dt}</Table.Td>
              <Table.Td>{r.activity_type}</Table.Td>
              <Table.Td>{n(r.sessions)}</Table.Td>
              <Table.Td>{n(r.avg_tracks_listened)}</Table.Td>
              <Table.Td>{n(r.avg_tracks_promoted)}</Table.Td>
              <Table.Td>{n(r.avg_tracks_deleted)}</Table.Td>
              <Table.Td>{fmtMs(r.p50_duration_ms)}</Table.Td>
              <Table.Td>{fmtMs(r.p90_duration_ms)}</Table.Td>
              <Table.Td>{fmtMs(r.p50_time_per_track_ms)}</Table.Td>
              <Table.Td>{fmtMs(r.p90_time_per_track_ms)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

export function SessionsTable({ userId, range }: { userId: string; range: AnalyticsRange }) {
  const { t } = useTranslation();
  const q = useSessions(userId, range);
  const rows: SessionRow[] = q.data?.sessions ?? [];

  if (q.isLoading) return <Loader size="sm" data-testid="loader" />;
  if (q.isError) return <Alert color="red" role="alert">{t('admin.analytics.load_failed')}</Alert>;
  if (rows.length === 0) return <Text c="dimmed">{t('admin.analytics.empty')}</Text>;

  return (
    <Table striped withTableBorder>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('admin.analytics.col.date')}</Table.Th>
          <Table.Th>{t('admin.analytics.col.activity')}</Table.Th>
          <Table.Th>{t('admin.analytics.col.seq')}</Table.Th>
          <Table.Th>{t('admin.analytics.col.start')}</Table.Th>
          <Table.Th>{t('admin.analytics.col.duration')}</Table.Th>
          <Table.Th>{t('admin.analytics.col.listened')}</Table.Th>
          <Table.Th>{t('admin.analytics.col.promoted')}</Table.Th>
          <Table.Th>{t('admin.analytics.col.deleted')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((r, i) => (
          <Table.Tr key={i}>
            <Table.Td>{r.dt}</Table.Td>
            <Table.Td>{r.activity_type}</Table.Td>
            <Table.Td>{n(r.session_seq)}</Table.Td>
            <Table.Td>{r.ts_start ?? '—'}</Table.Td>
            <Table.Td>{fmtMs(r.duration_ms)}</Table.Td>
            <Table.Td>{n(r.tracks_listened)}</Table.Td>
            <Table.Td>{n(r.tracks_promoted)}</Table.Td>
            <Table.Td>{n(r.tracks_deleted)}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
