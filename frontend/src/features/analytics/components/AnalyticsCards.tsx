import {
  Alert,
  Card,
  Group,
  Progress,
  SegmentedControl,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
} from '@mantine/core';
import { BarChart } from '@mantine/charts';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useFunnel, useListening } from '../hooks/useAnalytics';

type Period = 'day' | 'week' | 'month';
const PERIODS: Period[] = ['day', 'week', 'month'];

// Loaded card heights (measured in the browser test) so the gray placeholder
// blocks, like HomeSkeleton's, don't make the page jump when data lands.
const LISTENING_H = 292;
const FUNNEL_H = 220;

/** 280 min → "4h 40m"; under an hour → "42m". Compact so three fit a phone row. */
export function fmtMinutes(ms: number): string {
  const total = Math.round(ms / 60_000);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/** Same chrome as the other home blocks: bordered card + small caps title. */
function AnalyticsCard({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
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
  if (q.isLoading) return <Skeleton height={LISTENING_H} radius="md" data-testid="listening-skeleton" />;

  return (
    <AnalyticsCard title={t('analytics.listening.title')}>
      {!q.data ? (
        <LoadFailed />
      ) : (
        <>
          <SimpleGrid cols={3} spacing="xs">
            {PERIODS.map((p) => (
              <Stack key={p} gap={2} data-testid={`listening-${p}`}>
                <Text size="xs" c="dimmed">
                  {t(`analytics.period.${p}`)}
                </Text>
                <Text ff="monospace" fz={{ base: 'lg', sm: 24 }} fw={600} lh={1.1}>
                  {fmtMinutes(q.data.totals[p].listened_ms)}
                </Text>
                <Text size="xs" c="dimmed">
                  {t('analytics.listening.tracks', { count: q.data.totals[p].tracks })}
                </Text>
              </Stack>
            ))}
          </SimpleGrid>
          <BarChart
            h={160}
            data={q.data.daily.map((d) => ({
              dt: d.dt.slice(5),
              minutes: Math.round(d.listened_ms / 60_000),
            }))}
            dataKey="dt"
            series={[{ name: 'minutes', label: t('analytics.listening.minutes'), color: 'indigo.6' }]}
          />
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
  const [period, setPeriod] = useState<Period>('month');
  const q = useFunnel(userId);
  const stages = q.data?.stages ?? [];
  const top = stages[0]?.[period] ?? 0;
  if (q.isLoading) return <Skeleton height={FUNNEL_H} radius="md" data-testid="funnel-skeleton" />;

  return (
    <AnalyticsCard
      title={t('analytics.funnel.title')}
      action={
        <SegmentedControl
          size="xs"
          value={period}
          onChange={(v) => setPeriod(v as Period)}
          data={PERIODS.map((p) => ({ value: p, label: t(`analytics.period.${p}`) }))}
        />
      }
    >
      {!q.data ? (
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
                </Group>
                <Progress value={top > 0 ? Math.min(100, (n / top) * 100) : 0} />
              </Stack>
            );
          })}
        </Stack>
      )}
    </AnalyticsCard>
  );
}
