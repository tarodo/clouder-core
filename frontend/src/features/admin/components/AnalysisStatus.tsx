import { Badge, Group, Paper, SimpleGrid, Stack, Text } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { api } from '../../../api/client';
import type { components } from '../../../api/schema';

dayjs.extend(relativeTime);

type Status = components['schemas']['AnalysisStatus'];

const POLL_MS = 30_000;
// The analyzer runs about once a day on the owner's PC; longer silence means it is off.
const STALE_DAYS = 3;

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed" tt="uppercase">
        {label}
      </Text>
      <Text fw={600} size="lg">
        {value.toLocaleString('en-US')}
      </Text>
    </Stack>
  );
}

/** Admin view of the external audio analyzer: when it last called in, what it found. */
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
        {data.analyzers.map((a) => (
          <Stack key={a.name} gap={4}>
            {data.analyzers.length > 1 && (
              <Text size="sm" fw={500}>
                {a.name}
              </Text>
            )}
            <SimpleGrid cols={{ base: 2, sm: 5 }}>
              <Stat label={t('admin.analysis_status.due')} value={a.due} />
              <Stat label={t('admin.analysis_status.ok')} value={a.ok} />
              <Stat label={t('admin.analysis_status.ai_detected')} value={a.ai_detected} />
              <Stat label={t('admin.analysis_status.failed')} value={a.failed} />
              <Stat label={t('admin.analysis_status.unusable')} value={a.unusable_source} />
            </SimpleGrid>
          </Stack>
        ))}
      </Stack>
    </Paper>
  );
}
