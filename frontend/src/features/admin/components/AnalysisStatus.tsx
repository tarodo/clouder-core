import { Badge, Group, Paper, Stack, Text } from '@mantine/core';
import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { api } from '../../../api/client';
import type { components } from '../../../api/schema';
import { AiBadge } from '../../playback/AiBadge';

dayjs.extend(relativeTime);

type Status = components['schemas']['AnalysisStatus'];

const POLL_MS = 30_000;
// The analyzer runs about once a day on the owner's PC; longer silence means it is off.
const STALE_DAYS = 3;

function Stat({ label, value, marker }: { label: string; value: number; marker?: ReactNode }) {
  return (
    <Group gap={6} wrap="nowrap">
      {marker}
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text size="sm" fw={600}>
        {value.toLocaleString('en-US')}
      </Text>
    </Group>
  );
}

// Wraps on a phone; rows stay tight.
const ROW = { gap: 'lg', style: { rowGap: 4 } } as const;

/** Admin view of the AI pair (ai_lofcz + ai_deezer): when it last called in, what it found, what is left. */
export function AnalysisStatus() {
  const { t } = useTranslation();
  // TanStack Query v5 skips interval refetches while the tab is hidden, so an idle
  // admin tab does not keep Aurora awake.
  const { data } = useQuery({
    queryKey: ['admin', 'analysisStatus'],
    queryFn: () => api<Status>('/admin/analysis/status'),
    refetchInterval: POLL_MS,
  });
  if (!data) return null;

  const last = data.last_claim_at ? dayjs(data.last_claim_at) : null;
  const silentDays = last ? dayjs().diff(last, 'day') : null;
  const [color, label] =
    last === null
      ? ['gray', t('admin.analysis_status.never')]
      : silentDays !== null && silentDays >= STALE_DAYS
        ? ['orange', t('admin.analysis_status.stale', { days: silentDays })]
        : ['green', t('admin.analysis_status.last_run', { ago: last.fromNow() })];

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between">
          <Text fw={600}>{t('admin.analysis_status.title')}</Text>
          <Badge color={color} variant="light">
            {label}
          </Badge>
        </Group>
        {last && (
          <Text size="xs" c="dimmed">
            {data.last_result_at
              ? t('admin.analysis_status.last_result', { ago: dayjs(data.last_result_at).fromNow() })
              : t('admin.analysis_status.no_results')}
          </Text>
        )}
        <Group {...ROW}>
          {(['high', 'medium', 'low'] as const).map((level) => (
            <Stat
              key={level}
              marker={<AiBadge verdict={level} />}
              label={t(`admin.analysis_status.level_${level}`)}
              value={data.pair[level]}
            />
          ))}
          <Stat label={t('admin.analysis_status.clean')} value={data.pair.clean} />
        </Group>
        <Group {...ROW}>
          <Text size="sm" c="dimmed">
            {t('admin.analysis_status.queue')}
          </Text>
          {(['waiting', 'analyzed', 'failed', 'unusable'] as const).map((key) => (
            <Stat key={key} label={t(`admin.analysis_status.${key}`)} value={data.queue[key]} />
          ))}
        </Group>
      </Stack>
    </Paper>
  );
}
