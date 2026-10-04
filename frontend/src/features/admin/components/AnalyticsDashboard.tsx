import {
  Alert,
  Card,
  Group,
  Loader,
  Progress,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { BarChart } from '@mantine/charts';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useFunnel, useListening } from '../hooks/useAnalytics';

type Period = 'day' | 'week' | 'month';
const PERIODS: Period[] = ['day', 'week', 'month'];

/** 84 min → "1 h 24 min"; under an hour → "42 min". */
export function fmtMinutes(ms: number): string {
  const total = Math.round(ms / 60_000);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h > 0 ? `${h} h ${m} min` : `${m} min`;
}

export function ListeningSection() {
  const { t } = useTranslation();
  const q = useListening();

  if (q.isLoading) return <Loader size="sm" data-testid="loader" />;
  if (q.isError || !q.data) {
    return <Alert color="red" role="alert">{t('admin.analytics.load_failed')}</Alert>;
  }

  const { totals, daily } = q.data;
  const chart = daily.map((d) => ({
    dt: d.dt.slice(5),
    minutes: Math.round(d.listened_ms / 60_000),
  }));

  return (
    <Stack gap="sm">
      <Title order={4}>{t('admin.analytics.listening.title')}</Title>
      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
        {PERIODS.map((p) => (
          <Card key={p} withBorder padding="md" radius="md" data-testid={`listening-${p}`}>
            <Stack gap={4}>
              <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
                {t(`admin.analytics.period.${p}`)}
              </Text>
              <Text ff="monospace" fz={28} fw={600} lh={1.1}>
                {fmtMinutes(totals[p].listened_ms)}
              </Text>
              <Text size="sm" c="dimmed">
                {t('admin.analytics.listening.tracks', { count: totals[p].tracks })}
              </Text>
            </Stack>
          </Card>
        ))}
      </SimpleGrid>
      <BarChart
        h={200}
        data={chart}
        dataKey="dt"
        series={[{ name: 'minutes', label: t('admin.analytics.listening.minutes'), color: 'indigo.6' }]}
      />
    </Stack>
  );
}

function pct(n: number, of: number): string {
  return of > 0 ? `${Math.round((n / of) * 100)}%` : '—';
}

export function FunnelSection() {
  const { t } = useTranslation();
  const [period, setPeriod] = useState<Period>('month');
  const q = useFunnel();

  if (q.isLoading) return <Loader size="sm" data-testid="loader" />;
  if (q.isError || !q.data) {
    return <Alert color="red" role="alert">{t('admin.analytics.load_failed')}</Alert>;
  }

  const stages = q.data.stages;
  const top = stages[0]?.[period] ?? 0;

  return (
    <Stack gap="sm">
      <Group justify="space-between" wrap="wrap" gap="sm">
        <Title order={4}>{t('admin.analytics.funnel.title')}</Title>
        <SegmentedControl
          size="xs"
          value={period}
          onChange={(v) => setPeriod(v as Period)}
          data={PERIODS.map((p) => ({ value: p, label: t(`admin.analytics.period.${p}`) }))}
        />
      </Group>
      <Card withBorder padding="md" radius="md">
        <Stack gap="md">
          {stages.map((s, i) => {
            const n = s[period];
            const prev = i > 0 ? stages[i - 1]![period] : null;
            return (
              <Stack key={s.stage} gap={4} data-testid={`funnel-${s.stage}`}>
                <Group justify="space-between" wrap="nowrap">
                  <Text size="sm">{t(`admin.analytics.funnel.${s.stage}`)}</Text>
                  <Group gap="xs" wrap="nowrap">
                    <Text ff="monospace" fw={600}>
                      {n}
                    </Text>
                    {prev !== null && (
                      <Text size="xs" c="dimmed">
                        {t('admin.analytics.funnel.of_prev', { pct: pct(n, prev) })}
                      </Text>
                    )}
                  </Group>
                </Group>
                <Progress value={top > 0 ? Math.min(100, (n / top) * 100) : 0} />
              </Stack>
            );
          })}
        </Stack>
      </Card>
    </Stack>
  );
}
