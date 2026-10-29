import {
  Alert,
  Card,
  Group,
  Progress,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Text,
} from '@mantine/core';
import { BarChart } from '@mantine/charts';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Ghost, GhostScope, useRemembered } from '../../../components/Ghost';
import {
  useFunnel,
  useListening,
  useTimePerTrack,
  type FunnelResponse,
  type ListeningResponse,
  type Stage,
  type TimePerTrackResponse,
  type TptCell,
  type TptRow,
} from '../hooks/useAnalytics';

type Period = 'day' | 'week' | 'month';
const PERIODS: Period[] = ['day', 'week', 'month'];

// Placeholder data a loading card renders as its ghost (components/Ghost): the same markup,
// so the card is as tall as the loaded one.
const GHOST_TOTAL = { listened_ms: 442 * 60_000, tracks: 138 };
const LISTENING_GHOST: ListeningResponse = {
  today: '',
  totals: { day: GHOST_TOTAL, week: GHOST_TOTAL, month: GHOST_TOTAL },
  daily: Array.from({ length: 30 }, (_, i) => ({ dt: `2026-09-${i + 1}`, ...GHOST_TOTAL })),
};
const FUNNEL_GHOST: FunnelResponse = {
  today: '',
  stages: (['triaged', 'categorized', 'playlisted'] as const).map((stage) => ({
    stage,
    day: 100,
    week: 100,
    month: 100,
  })),
};
const GHOST_CELL = { n: 1_000, p50_ms: 42_000, p90_ms: 118_000 };
const tptGhost = (rows: number): TimePerTrackResponse => ({
  days: 30,
  stages: ['triage', 'category', 'playlist'],
  rows: Array.from({ length: rows }, (_, i) => ({
    style_id: i === 0 ? '*' : `ghost-${i}`,
    style_name: 'Placeholder',
    cells: { triage: GHOST_CELL, category: GHOST_CELL, playlist: GHOST_CELL },
  })),
});

/** 280 min → "4h 40m"; under an hour → "42m". Compact so three fit a phone row. */
export function fmtMinutes(ms: number): string {
  const total = Math.round(ms / 60_000);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/** Same chrome as the other home blocks: bordered card + small caps title. A `ghost` card is
 * still loading: its content is the placeholder data under Ghost bars. */
function AnalyticsCard(props: { title: string; action?: ReactNode; ghost: boolean; children: ReactNode }) {
  const { title, action, ghost, children } = props;
  return (
    <GhostScope on={ghost}>
      <Card withBorder padding="md" radius="md">
        <Stack gap="sm">
          <Group justify="space-between" wrap="wrap" gap="xs">
            <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
              {title}
            </Text>
            {action}
          </Group>
          {children}
        </Stack>
      </Card>
    </GhostScope>
  );
}

function LoadFailed() {
  const { t } = useTranslation();
  return (
    <Alert color="red" variant="light" role="alert">
      {t('analytics.load_failed')}
    </Alert>
  );
}

export function ListeningCard({ userId = '' }: { userId?: string }) {
  const { t } = useTranslation();
  const q = useListening(userId);
  const data = q.isLoading ? LISTENING_GHOST : q.data;

  return (
    <AnalyticsCard title={t('analytics.listening.title')} ghost={q.isLoading}>
      {!data ? (
        <LoadFailed />
      ) : (
        <>
          <SimpleGrid cols={3} spacing="xs">
            {PERIODS.map((p) => (
              <Stack key={p} gap={2} data-testid={`listening-${p}`}>
                <Text size="xs" c="dimmed">
                  {t(`analytics.period.${p}`)}
                </Text>
                <Ghost>
                  <Text ff="monospace" fz={{ base: 'lg', sm: 24 }} fw={600} lh={1.1}>
                    {fmtMinutes(data.totals[p].listened_ms)}
                  </Text>
                </Ghost>
                <Ghost>
                  <Text size="xs" c="dimmed">
                    {t('analytics.listening.tracks', { count: data.totals[p].tracks })}
                  </Text>
                </Ghost>
              </Stack>
            ))}
          </SimpleGrid>
          <Ghost block>
            <BarChart
              h={160}
              data={data.daily.map((d) => ({
                dt: d.dt.slice(5),
                minutes: Math.round(d.listened_ms / 60_000),
              }))}
              dataKey="dt"
              series={[{ name: 'minutes', label: t('analytics.listening.minutes'), color: 'indigo.6' }]}
            />
          </Ghost>
        </>
      )}
    </AnalyticsCard>
  );
}

function pct(n: number, of: number): string {
  return of > 0 ? `${Math.round((n / of) * 100)}%` : '—';
}

export function FunnelCard({ userId = '' }: { userId?: string }) {
  const { t } = useTranslation();
  const [period, setPeriod] = useState<Period>('week');
  const q = useFunnel(userId);
  const data = q.isLoading ? FUNNEL_GHOST : q.data;
  const stages = data?.stages ?? [];
  const top = stages[0]?.[period] ?? 0;

  return (
    <AnalyticsCard
      title={t('analytics.funnel.title')}
      ghost={q.isLoading}
      action={
        <SegmentedControl
          size="xs"
          value={period}
          onChange={(v) => setPeriod(v as Period)}
          data={PERIODS.map((p) => ({ value: p, label: t(`analytics.period.${p}`) }))}
        />
      }
    >
      {!data ? (
        <LoadFailed />
      ) : (
        <Stack gap="md">
          {stages.map((s, i) => {
            const n = s[period];
            const prev = i > 0 ? stages[i - 1]![period] : null;
            return (
              <Stack key={s.stage} gap={4} data-testid={`funnel-${s.stage}`}>
                <Group justify="space-between" wrap="nowrap">
                  <Text size="sm">{t(`analytics.funnel.${s.stage}`)}</Text>
                  <Ghost>
                    <Group gap="xs" wrap="nowrap">
                      <Text ff="monospace" fw={600}>
                        {n}
                      </Text>
                      {prev !== null && (
                        <Text size="xs" c="dimmed">
                          {t('analytics.funnel.of_prev', { pct: pct(n, prev) })}
                        </Text>
                      )}
                    </Group>
                  </Ghost>
                </Group>
                <Ghost block>
                  <Progress value={top > 0 ? Math.min(100, (n / top) * 100) : 0} />
                </Ghost>
              </Stack>
            );
          })}
        </Stack>
      )}
    </AnalyticsCard>
  );
}

/** p90 on fewer plays is noise: show it only from this many plays up. */
export const MIN_N_P90 = 20;
const STAGES: Stage[] = ['triage', 'category', 'playlist'];

/** Compact so a phone fits three stage columns: "6s", "84s", "208s"; 10 min+ → "12m". */
export function fmtSec(ms: number): string {
  const s = Math.round(ms / 1000);
  return s < 600 ? `${s}s` : `${Math.round(s / 60)}m`;
}

/** 980 → "980", 2303 → "2.3k", 12345 → "12k". */
export function fmtCount(n: number): string {
  if (n < 1000) return String(n);
  return n < 10_000 ? `${(n / 1000).toFixed(1)}k` : `${Math.round(n / 1000)}k`;
}

function TptValue({ cell }: { cell: TptCell | null }) {
  if (!cell) {
    return (
      <Text size="sm" c="dimmed">
        —
      </Text>
    );
  }
  return (
    <Stack gap={0} align="flex-end">
      <Ghost>
        <Text size="sm" ff="monospace" fw={600}>
          {fmtSec(cell.p50_ms)}
        </Text>
      </Ghost>
      <Ghost>
        <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
          {cell.n >= MIN_N_P90 ? fmtSec(cell.p90_ms) : '—'} · {fmtCount(cell.n)}
        </Text>
      </Ghost>
    </Stack>
  );
}

export function TimePerTrackCard({ userId = '' }: { userId?: string }) {
  const { t } = useTranslation();
  const [days, setDays] = useState<30 | 90>(30);
  const q = useTimePerTrack(userId, days);
  const rows = useRemembered(`analytics.tpt.${userId}`, q.data?.rows.length, 2);
  const data = q.isLoading ? tptGhost(rows) : q.data;

  const styleLabel = (r: TptRow) =>
    r.style_id === '*'
      ? t('analytics.tpt.all_styles')
      : r.style_id === null
        ? t('analytics.tpt.unknown_style')
        : (r.style_name ?? r.style_id.slice(0, 8));

  return (
    <AnalyticsCard
      title={t('analytics.tpt.title')}
      ghost={q.isLoading}
      action={
        <SegmentedControl
          size="xs"
          value={String(days)}
          onChange={(v) => setDays(v === '90' ? 90 : 30)}
          data={[
            { value: '30', label: t('analytics.period.month') },
            { value: '90', label: t('analytics.tpt.days_90') },
          ]}
        />
      }
    >
      {!data ? (
        <LoadFailed />
      ) : data.rows.length === 0 ? (
        <Ghost>
          <Text size="sm" c="dimmed">
            {t('analytics.tpt.empty')}
          </Text>
        </Ghost>
      ) : (
        <>
          <Table layout="fixed" withRowBorders={false} verticalSpacing={4} horizontalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th w="28%" />
                {STAGES.map((s) => (
                  <Table.Th key={s} ta="right">
                    <Text size="xs" c="dimmed" fw={500}>
                      {t(`analytics.tpt.stage.${s}`)}
                    </Text>
                  </Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.rows.map((r) => (
                <Table.Tr key={r.style_id ?? 'unknown'}>
                  <Table.Td>
                    <Ghost>
                      <Text size="sm" truncate fw={r.style_id === '*' ? 600 : 400} title={styleLabel(r)}>
                        {styleLabel(r)}
                      </Text>
                    </Ghost>
                  </Table.Td>
                  {STAGES.map((s) => (
                    <Table.Td key={s} ta="right" data-testid={`tpt-${r.style_id ?? 'unknown'}-${s}`}>
                      <TptValue cell={r.cells[s]} />
                    </Table.Td>
                  ))}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          <Text size="xs" c="dimmed">
            {t('analytics.tpt.legend', { min: MIN_N_P90 })}
          </Text>
        </>
      )}
    </AnalyticsCard>
  );
}
