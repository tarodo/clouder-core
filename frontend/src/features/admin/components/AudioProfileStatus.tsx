import { Group, Paper, Stack, Text } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { api } from '../../../api/client';
import type { components } from '../../../api/schema';
import { ROW, Stat } from './AnalysisStatus';

dayjs.extend(relativeTime);

type Status = components['schemas']['AnalysisStatus'];

/** Admin view of the light audio profile queue and the trained triage models. */
export function AudioProfileStatus() {
  const { t } = useTranslation();
  // Same key as the AI card: one fetch feeds both.
  const { data } = useQuery({
    queryKey: ['admin', 'analysisStatus'],
    queryFn: () => api<Status>('/admin/analysis/status'),
    refetchInterval: 30_000,
  });
  if (!data) return null;
  const { profile, models } = data;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Text fw={600}>{t('admin.profile_status.title')}</Text>
        <Group {...ROW}>
          <Text size="sm" c="dimmed">
            {t('admin.profile_status.queue')}
          </Text>
          {(['waiting', 'profiled', 'failed', 'unusable'] as const).map((key) => (
            <Stat key={key} label={t(`admin.profile_status.${key}`)} value={profile[key]} />
          ))}
        </Group>
        <Text size="xs" c="dimmed">
          {models.count > 0 && models.last_trained_at
            ? t('admin.profile_status.models', {
                count: models.count,
                ago: dayjs(models.last_trained_at).fromNow(),
              })
            : t('admin.profile_status.models_none')}
        </Text>
      </Stack>
    </Paper>
  );
}
