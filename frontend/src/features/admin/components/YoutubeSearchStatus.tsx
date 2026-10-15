import { Badge, Group, Paper, SimpleGrid, Stack, Text } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api } from '../../../api/client';
import type { components } from '../../../api/schema';

type SearchStatus = components['schemas']['YoutubeSearchStatus'];

const POLL_MS = 30_000;

const BADGE_COLOR: Record<SearchStatus['status'], string> = {
  running: 'green',
  queued: 'blue',
  paused: 'orange',
  idle: 'gray',
};

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

/** Admin view of the ingest-time YouTube search: backlog, pace and outcomes. */
export function YoutubeSearchStatus() {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: ['admin', 'youtubeSearchStatus'],
    queryFn: () => api<SearchStatus>('/admin/youtube/search-status'),
    refetchInterval: POLL_MS,
  });
  if (!data) return null;

  const label =
    data.status === 'paused' && data.paused_until
      ? t('admin.youtube_status.paused_until', {
          time: new Date(data.paused_until).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        })
      : t(`admin.youtube_status.${data.status}`);

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between">
          <Text fw={600}>{t('admin.youtube_status.title')}</Text>
          <Badge color={BADGE_COLOR[data.status]} variant="light">
            {label}
          </Badge>
        </Group>
        <SimpleGrid cols={{ base: 2, sm: 3 }}>
          <Stat label={t('admin.youtube_status.waiting')} value={data.tracks.waiting} />
          <Stat label={t('admin.youtube_status.recent')} value={data.tracks.searched_last_10_min} />
          <Stat label={t('admin.youtube_status.searched')} value={data.tracks.searched_total} />
        </SimpleGrid>
        <SimpleGrid cols={{ base: 2, sm: 4 }}>
          <Stat label={t('admin.youtube_status.matched')} value={data.results.matched} />
          <Stat label={t('admin.youtube_status.needs_review')} value={data.results.needs_review} />
          <Stat label={t('admin.youtube_status.not_found')} value={data.results.not_found} />
          <Stat label={t('admin.youtube_status.videos')} value={data.results.videos} />
        </SimpleGrid>
      </Stack>
    </Paper>
  );
}
