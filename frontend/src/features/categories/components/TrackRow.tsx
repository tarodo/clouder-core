import { Card, Group, Stack, Table, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { Fragment, type ReactNode } from 'react';
import {
  formatAdded,
  formatCommentCount,
  formatLength,
  formatReleaseDate,
} from '../../../lib/formatters';
import type { CategoryTrack } from '../hooks/useCategoryTracks';
import { TrackTagsCell } from '../../tags';
import { UsedInPlaylistBadge } from './UsedInPlaylistBadge';
import { TrackKey } from '../../playback/TrackKey';
import { PlayPauseButton } from '../../playback/PlayPauseButton';
import { AiBadge } from '../../playback/AiBadge';
import { AiRepBadge } from '../../library/components/AiRepBadge';
import { ArtistLinks, EntityLink } from '../../library/components/EntityLinks';

/** The table's optional columns, in order; the title and the actions always show. */
export const TRACK_COLUMNS = [
  'tags',
  'artists',
  'label',
  'key',
  'bpm',
  'comments',
  'length',
  'released',
  'added',
] as const;
export type TrackColumn = (typeof TRACK_COLUMNS)[number];

// A cell that truncates instead of wrapping, so every row stays one title-and-mix high: max-width 0
// lets the column shrink to min-width and share the spare room. No percentage width: Chrome then
// squeezes the other columns below their content.
const fill = (minWidth: number) => ({ maxWidth: 0, minWidth });
const nowrap = { whiteSpace: 'nowrap' } as const;

export interface TrackRowProps {
  track: CategoryTrack;
  variant: 'desktop' | 'mobile';
  /** Desktop: the columns the user turned off. */
  hidden?: readonly TrackColumn[];
  actions?: ReactNode;
  onPlay?: () => void;
  isCurrent?: boolean;
  isPlaying?: boolean;
  onToggle?: () => void;
}

export function TrackRow({
  track,
  variant,
  hidden = [],
  actions,
  onPlay,
  isCurrent,
  isPlaying,
  onToggle,
}: TrackRowProps) {
  const { t } = useTranslation();
  const tagsCell = <TrackTagsCell tags={track.tags} />;
  const artists = track.artists.length ? <ArtistLinks artists={track.artists} /> : '—';
  const label = track.label ? (
    <>
      <EntityLink kind="label" id={track.label.id} name={track.label.name} />
      <AiRepBadge rep={track.label.ai} ml={4} />
    </>
  ) : null;

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
    const cells: Record<TrackColumn, ReactNode> = {
      tags: (
        <Table.Td style={nowrap}>
          {/* max-content: Chrome sizes a flex row of overflow-hidden badges as if they could
              shrink to nothing, and the column comes out narrower than its tags */}
          <Group gap={4} wrap="nowrap" style={{ minWidth: 'max-content' }}>
            {track.used_in_playlist && <UsedInPlaylistBadge />}
            <TrackTagsCell tags={track.tags} max={4} />
          </Group>
        </Table.Td>
      ),
      artists: (
        <Table.Td style={fill(70)}>
          <Text inherit truncate>
            {artists}
          </Text>
        </Table.Td>
      ),
      label: (
        <Table.Td style={fill(70)}>
          <Text inherit truncate>
            {label ?? '—'}
          </Text>
        </Table.Td>
      ),
      key: (
        <Table.Td style={nowrap}>
          <TrackKey camelot={track.key_camelot} name={track.key_name} />
        </Table.Td>
      ),
      bpm: (
        <Table.Td className="font-mono" style={nowrap}>
          {track.bpm ?? '—'}
        </Table.Td>
      ),
      comments: (
        <Table.Td className="font-mono" style={nowrap}>
          {formatCommentCount(track.comment_count)}
        </Table.Td>
      ),
      length: (
        <Table.Td className="font-mono" style={nowrap}>
          {formatLength(track.length_ms)}
        </Table.Td>
      ),
      released: (
        <Table.Td className="font-mono" style={nowrap}>
          {formatReleaseDate(track.spotify_release_date)}
        </Table.Td>
      ),
      added: (
        <Table.Td className="font-mono" style={nowrap}>
          {formatAdded(track.added_at)}
        </Table.Td>
      ),
    };
    return (
      <Table.Tr
        data-current={isCurrent ? 'true' : undefined}
        bg={isCurrent ? 'var(--mantine-color-default-hover)' : undefined}
      >
        <Table.Td style={fill(170)}>
          <Group gap="xs" wrap="nowrap">
            {playButton}
            {/* the mix line is always there, so a row without a mix is as high as the rest */}
            <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
              <Group gap={6} wrap="nowrap">
                <Text fw={500} truncate>
                  {track.title}
                </Text>
                <AiBadge verdict={track.ai_verdict} />
              </Group>
              <Text size="xs" c="dimmed" truncate>
                {track.mix_name || '\u00a0'}
              </Text>
            </Stack>
          </Group>
        </Table.Td>
        {TRACK_COLUMNS.filter((c) => !hidden.includes(c)).map((c) => (
          <Fragment key={c}>{cells[c]}</Fragment>
        ))}
        <Table.Td style={{ width: 1, ...nowrap }}>{actions ?? null}</Table.Td>
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
            {artists}
            {label ? (
              <Text span c="dimmed" inherit>
                {' · '}
                {label}
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
