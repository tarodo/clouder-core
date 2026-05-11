import { Card, Group, Stack, Table, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { ReactNode } from 'react';
import { formatAdded, formatLength, formatReleaseDate } from '../../../lib/formatters';
import type { CategoryTrack } from '../hooks/useCategoryTracks';
import { TrackTagsCell } from '../../tags';

function joinArtists(artists: CategoryTrack['artists']): string {
  return artists.map((a) => a.name).join(', ');
}

export interface TrackRowProps {
  track: CategoryTrack;
  variant: 'desktop' | 'mobile';
  categoryId: string;
  actions?: ReactNode;
}

export function TrackRow({ track, variant, categoryId, actions }: TrackRowProps) {
  const { t } = useTranslation();
  const aiBadge = track.is_ai_suspected ? (
    <IconAlertTriangle
      size={14}
      aria-label={t('categories.tracks_table.ai_suspected_aria')}
      color="var(--color-warning)"
    />
  ) : null;
  const tagsCell = (
    <TrackTagsCell categoryId={categoryId} trackId={track.id} tags={track.tags} />
  );

  if (variant === 'desktop') {
    return (
      <Table.Tr>
        <Table.Td>
          <Group gap="xs" wrap="nowrap">
            {aiBadge}
            <Stack gap={0}>
              <Text fw={500}>{track.title}</Text>
              {track.mix_name && (
                <Text size="xs" c="dimmed">{track.mix_name}</Text>
              )}
            </Stack>
          </Group>
        </Table.Td>
        <Table.Td>{tagsCell}</Table.Td>
        <Table.Td>{joinArtists(track.artists)}</Table.Td>
        <Table.Td>{track.label?.name ?? '—'}</Table.Td>
        <Table.Td className="font-mono">{track.bpm ?? '—'}</Table.Td>
        <Table.Td className="font-mono">{formatLength(track.length_ms)}</Table.Td>
        <Table.Td className="font-mono">
          {formatReleaseDate(track.spotify_release_date)}
        </Table.Td>
        <Table.Td>{formatAdded(track.added_at)}</Table.Td>
        <Table.Td style={{ width: 40 }}>{actions ?? null}</Table.Td>
      </Table.Tr>
    );
  }

  return (
    <Card withBorder padding="sm" style={{ position: 'relative' }}>
      {actions && (
        <div style={{ position: 'absolute', top: 8, right: 8 }}>{actions}</div>
      )}
      <Stack gap={4}>
        <Group gap="xs">
          {aiBadge}
          <Text fw={500}>{track.title}</Text>
        </Group>
        {track.mix_name && (
          <Text size="xs" c="dimmed">{track.mix_name}</Text>
        )}
        <Text size="sm">{joinArtists(track.artists)}</Text>
        {track.label && (
          <Text size="xs" c="dimmed">{track.label.name}</Text>
        )}
        <div>{tagsCell}</div>
        <Group gap="md" mt={4}>
          <Text size="xs" c="dimmed" className="font-mono">
            {track.bpm ?? '—'} BPM
          </Text>
          <Text size="xs" c="dimmed" className="font-mono">
            {formatLength(track.length_ms)}
          </Text>
          {track.spotify_release_date && (
            <Text size="xs" c="dimmed" className="font-mono">
              {track.spotify_release_date}
            </Text>
          )}
          <Text size="xs" c="dimmed">{formatAdded(track.added_at)}</Text>
        </Group>
      </Stack>
    </Card>
  );
}
