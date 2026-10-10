import { Badge, Group, Paper, SimpleGrid, Stack, Text } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api } from '../../../api/client';
import type { components } from '../../../api/schema';

type SearchStatus = components['schemas']['SpotifySearchStatus'];

export const SPOTIFY_STATUS_POLL_MS = 10_000;

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

export function SpotifySearchStatus() {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: ['admin', 'spotifySearchStatus'],
    queryFn: () => api<SearchStatus>('/admin/spotify/search-status'),
    refetchInterval: SPOTIFY_STATUS_POLL_MS,
  });
  if (!data) return null;

  const label =
    data.status === 'paused' && data.paused_until
      ? t('admin.spotify_status.paused_until', {
          time: new Date(data.paused_until).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        })
      : t(`admin.spotify_status.${data.status}`);

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between">
          <Text fw={600}>{t('admin.spotify_status.title')}</Text>
          <Badge color={BADGE_COLOR[data.status]} variant="light">
            {label}
          </Badge>
        </Group>
        <SimpleGrid cols={{ base: 1, sm: 3 }}>
          <Stat label={t('admin.spotify_status.waiting')} value={data.tracks.waiting} />
          <Stat label={t('admin.spotify_status.recent')} value={data.tracks.searched_last_10_min} />
          <Stat label={t('admin.spotify_status.not_found')} value={data.tracks.not_found} />
        </SimpleGrid>
      </Stack>
    </Paper>
  );
}
