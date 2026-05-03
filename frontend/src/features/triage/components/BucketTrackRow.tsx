import { Card, Group, Stack, Table, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { IconAlertTriangle } from '../../../components/icons';
import { formatLength, formatReleaseDate } from '../../../lib/formatters';
import type { BucketTrack } from '../hooks/useBucketTracks';
import type { TriageBucket } from '../lib/bucketLabels';
import { MoveToMenu } from './MoveToMenu';

export interface BucketTrackRowProps {
  track: BucketTrack;
  variant: 'desktop' | 'mobile';
  buckets: TriageBucket[];
  currentBucketId: string;
  onMove: (toBucket: TriageBucket) => void;
  onTransfer?: () => void;
  showMoveMenu: boolean;
  blockStatus?: 'IN_PROGRESS' | 'FINALIZED';
}

export function BucketTrackRow({
  track,
  variant,
  buckets,
  currentBucketId,
  onMove,
  onTransfer,
  showMoveMenu,
  blockStatus,
}: BucketTrackRowProps) {
  const { t } = useTranslation();
  const aiBadge = track.is_ai_suspected ? (
    <IconAlertTriangle
      size={14}
      aria-label={t('triage.tracks_table.ai_suspected_aria')}
      color="var(--color-warning)"
    />
  ) : null;
  const moveMenu = showMoveMenu ? (
    <MoveToMenu
      buckets={buckets}
      currentBucketId={currentBucketId}
      onMove={onMove}
      onTransfer={onTransfer}
      showTransfer={blockStatus === 'IN_PROGRESS' && !!onTransfer}
    />
  ) : null;

  if (variant === 'desktop') {
    return (
      <Table.Tr>
        <Table.Td>
          <Group gap="xs" wrap="nowrap">
            {aiBadge}
            <Stack gap={0}>
              <Text fw={500}>{track.title}</Text>
              {track.mix_name && (
                <Text size="xs" c="dimmed">
                  {track.mix_name}
                </Text>
              )}
            </Stack>
          </Group>
        </Table.Td>
        <Table.Td>{track.artists.join(', ') || '—'}</Table.Td>
        <Table.Td>{track.label_name ?? '—'}</Table.Td>
        <Table.Td className="font-mono">{track.bpm ?? '—'}</Table.Td>
        <Table.Td className="font-mono">{formatLength(track.length_ms)}</Table.Td>
        <Table.Td className="font-mono">{formatReleaseDate(track.spotify_release_date)}</Table.Td>
        <Table.Td>{moveMenu}</Table.Td>
      </Table.Tr>
    );
  }

  return (
    <Card withBorder padding="sm">
      <Stack gap={4}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Group gap="xs">
            {aiBadge}
            <Text fw={500}>{track.title}</Text>
          </Group>
          {moveMenu}
        </Group>
        {track.mix_name && (
          <Text size="xs" c="dimmed">
            {track.mix_name}
          </Text>
        )}
        <Text size="sm">{track.artists.join(', ') || '—'}</Text>
        {track.label_name && (
          <Text size="xs" c="dimmed">
            {track.label_name}
          </Text>
        )}
        <Group gap="md" mt={4}>
          <Text size="xs" c="dimmed" className="font-mono">
            {track.bpm ?? '—'} BPM
          </Text>
          <Text size="xs" c="dimmed" className="font-mono">
            {formatLength(track.length_ms)}
          </Text>
          <Text size="xs" c="dimmed" className="font-mono">
            {formatReleaseDate(track.spotify_release_date)}
          </Text>
        </Group>
        {track.publish_date && (
          <Text size="xs" c="dimmed">
            Beatport: {track.publish_date}
          </Text>
        )}
      </Stack>
    </Card>
  );
}
