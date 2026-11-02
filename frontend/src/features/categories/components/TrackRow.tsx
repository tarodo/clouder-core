import { Card, Group, Stack, Table, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { ReactNode } from 'react';
import { formatAdded, formatLength, formatReleaseDate } from '../../../lib/formatters';
import type { CategoryTrack } from '../hooks/useCategoryTracks';
import { TrackTagsCell } from '../../tags';
import { UsedInPlaylistBadge } from './UsedInPlaylistBadge';
import { TrackKey } from '../../playback/TrackKey';
import { PlayPauseButton } from '../../playback/PlayPauseButton';
import { AiBadge } from '../../playback/AiBadge';
import { AiRepBadge, NamesWithAi } from '../../library/components/AiRepBadge';

export interface TrackRowProps {
  track: CategoryTrack;
  variant: 'desktop' | 'mobile';
  actions?: ReactNode;
  onPlay?: () => void;
  isCurrent?: boolean;
  isPlaying?: boolean;
  onToggle?: () => void;
}

export function TrackRow({ track, variant, actions, onPlay, isCurrent, isPlaying, onToggle }: TrackRowProps) {
  const { t } = useTranslation();
  const tagsCell = <TrackTagsCell tags={track.tags} />;

  const canPlay = !!onPlay && !!track.spotify_id;
  const playButton = onPlay ? (
    <PlayPauseButton
      isCurrent={!!isCurrent}
      isPlaying={!!isPlaying}
      canPlay={canPlay}
      onPlay={onPlay}
      onToggle={onToggle ?? onPlay}
      playLabel={t('categories.tracks_table.play_aria')}
      pauseLabel={t('categories.tracks_table.pause_aria')}
      unavailableLabel={t('categories.tracks_table.play_unavailable')}
    />
  ) : null;

  if (variant === 'desktop') {
    return (
      <Table.Tr
        data-current={isCurrent ? 'true' : undefined}
        bg={isCurrent ? 'var(--mantine-color-default-hover)' : undefined}
      >
        <Table.Td>
          <Group gap="xs" wrap="nowrap">
            {playButton}
            <Stack gap={0}>
              <Group gap={6} wrap="nowrap">
                <Text fw={500}>{track.title}</Text>
                <AiBadge verdict={track.ai_verdict} />
              </Group>
              {track.mix_name && (
                <Text size="xs" c="dimmed">{track.mix_name}</Text>
              )}
            </Stack>
          </Group>
        </Table.Td>
        <Table.Td>
          <Group gap="xs" wrap="wrap">
            {tagsCell}
            {track.used_in_playlist && <UsedInPlaylistBadge />}
          </Group>
        </Table.Td>
        <Table.Td><NamesWithAi items={track.artists} /></Table.Td>
        <Table.Td><NamesWithAi items={track.label ? [track.label] : []} /></Table.Td>
        <Table.Td><TrackKey camelot={track.key_camelot} name={track.key_name} /></Table.Td>
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
    <Card
      withBorder
      padding="xs"
      data-current={isCurrent ? 'true' : undefined}
      bg={isCurrent ? 'var(--mantine-color-default-hover)' : undefined}
    >
      {/* three lines: title + mix, artists + label, BPM / key / date + tags */}
      <Group gap="xs" wrap="nowrap">
        {playButton}
        <Stack gap={2} miw={0} style={{ flex: 1 }}>
          <Group gap={6} wrap="nowrap">
            <Text size="sm" truncate>
              <Text span fw={500} inherit>
                {track.title}
              </Text>
              {track.mix_name ? (
                <>
                  {' '}
                  <Text span size="xs" c="dimmed">
                    {track.mix_name}
                  </Text>
                </>
              ) : null}
            </Text>
            <AiBadge verdict={track.ai_verdict} />
          </Group>
          <Text size="xs" truncate>
            <NamesWithAi items={track.artists} />
            {track.label ? (
              <Text span c="dimmed" inherit>
                {' · '}
                <span>{track.label.name}</span>
                <AiRepBadge rep={track.label.ai} ml={4} />
              </Text>
            ) : null}
          </Text>
          <Group gap={8} wrap="wrap">
            <Text size="xs" c="dimmed" className="font-mono">
              {track.bpm ?? '—'} BPM
            </Text>
            <TrackKey camelot={track.key_camelot} name={track.key_name} size="xs" />
            <Text size="xs" c="dimmed" className="font-mono">
              {formatReleaseDate(track.spotify_release_date)}
            </Text>
            {track.used_in_playlist && <UsedInPlaylistBadge />}
            {tagsCell}
          </Group>
        </Stack>
        {actions}
      </Group>
    </Card>
  );
}
