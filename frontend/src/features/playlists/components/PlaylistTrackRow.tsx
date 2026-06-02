import type { CSSProperties, HTMLAttributes } from 'react';
import { ActionIcon, Button, Group, Stack, Text } from '@mantine/core';
import { useSortable, type AnimateLayoutChanges } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import {
  IconBrandSpotify,
  IconGripVertical,
  IconLink,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { PlaylistTrack } from '../lib/playlistTypes';
import { beatportTrackUrl } from '../lib/playlistExport';
import { formatLength, formatReleaseDate } from '../../../lib/formatters';
import { TagPill } from '../../tags';
import { YtMusicBadge } from './YtMusicBadge';
import { TrackKey } from '../../playback/TrackKey';
import { PlayPauseButton } from '../../playback/PlayPauseButton';

export interface PlaylistTrackRowProps {
  track: PlaylistTrack;
  position: number;
  onRemove: (track: PlaylistTrack) => void;
  reorderDisabled?: boolean;
  onPlay?: () => void;
  isCurrent?: boolean;
  isPlaying?: boolean;
  onToggle?: () => void;
  playlistId: string;
}

interface ViewProps extends PlaylistTrackRowProps {
  /** Sortable node ref + transform style (omitted for the drag-overlay clone). */
  rootRef?: (el: HTMLElement | null) => void;
  rootStyle?: CSSProperties;
  /** Drag-handle listeners/attributes (omitted for the overlay clone). */
  handleProps?: HTMLAttributes<HTMLButtonElement>;
  /** True when rendered inside the DragOverlay (lifts the tile visually). */
  overlay?: boolean;
}

/**
 * Presentational track tile. Shared by the sortable row and the DragOverlay
 * clone so the dragged tile is visually identical while living in its own layer.
 */
export function PlaylistTrackRowView({
  track,
  position,
  onRemove,
  reorderDisabled = false,
  onPlay,
  isCurrent,
  isPlaying,
  onToggle,
  playlistId,
  rootRef,
  rootStyle,
  handleProps,
  overlay = false,
}: ViewProps) {
  const { t } = useTranslation();
  const canPlay = !!onPlay && !!track.spotify_id;
  const artistNames = track.artists.map((a) => a.name).join(', ');
  const groupStyle: CSSProperties = overlay
    ? { ...rootStyle, boxShadow: 'var(--mantine-shadow-md)', cursor: 'grabbing' }
    : rootStyle ?? {};

  return (
    <Group
      ref={rootRef}
      style={groupStyle}
      data-current={isCurrent ? 'true' : undefined}
      gap="sm"
      wrap="nowrap"
      p="xs"
      bg={isCurrent ? 'var(--mantine-color-default-hover)' : 'var(--color-bg-elevated)'}
      bd="1px solid var(--color-border)"
    >
      {/* Drag handle */}
      <ActionIcon
        variant="subtle"
        aria-label="Drag handle"
        disabled={reorderDisabled}
        aria-roledescription="sortable"
        style={{ cursor: reorderDisabled ? 'not-allowed' : 'grab', touchAction: 'none' }}
        {...handleProps}
      >
        <IconGripVertical size={18} />
      </ActionIcon>

      {/* Position number */}
      <Text fw={500} size="sm" style={{ minWidth: 32 }}>
        {position}.
      </Text>

      {/* Play / Pause button (only when the page wires playback) */}
      {onPlay !== undefined && (
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
      )}

      {/* Track info — two lines: title/mix/artists, then meta + editable tags */}
      <Stack gap={2} flex={1} style={{ minWidth: 0 }}>
        <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
          <Text fw={500} truncate>
            {track.title}
          </Text>
          {track.mix_name && (
            <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
              {track.mix_name}
            </Text>
          )}
          {artistNames && (
            <Text size="sm" c="dimmed" truncate>
              {artistNames}
            </Text>
          )}
        </Group>
        <Group gap="xs" wrap="wrap" align="center">
          <TrackKey camelot={track.key_camelot} name={track.key_name} size="xs" />
          <Text size="xs" c="dimmed">
            {[
              track.label?.name ?? '—',
              track.bpm != null ? `${track.bpm} BPM` : null,
              // formatLength/formatReleaseDate return '—' for null, so guard
              // here to truly omit missing parts (no "| — | —" gaps).
              track.length_ms ? formatLength(track.length_ms) : null,
              track.spotify_release_date
                ? formatReleaseDate(track.spotify_release_date)
                : null,
            ]
              .filter(Boolean)
              .join(' | ')}
          </Text>
          {/* Read-only in the list — tags are edited in the player. */}
          {track.tags.map((tag) => (
            <TagPill key={tag.id} name={tag.name} color={tag.color} />
          ))}
        </Group>
      </Stack>

      {/* Spotify external link */}
      {track.spotify_id && (
        <ActionIcon
          component="a"
          href={`https://open.spotify.com/track/${track.spotify_id}`}
          target="_blank"
          rel="noopener noreferrer"
          variant="subtle"
          color="gray"
          aria-label={t('playlists.publish.open_in_spotify')}
        >
          <IconBrandSpotify size={16} />
        </ActionIcon>
      )}

      {/* Beatport external link */}
      {track.beatport_track_id && (
        <ActionIcon
          component="a"
          href={beatportTrackUrl(track.beatport_track_id, track.beatport_slug) ?? undefined}
          target="_blank"
          rel="noopener noreferrer"
          variant="subtle"
          color="gray"
          aria-label={t('playlists.detail.open_beatport')}
        >
          <IconLink size={16} />
        </ActionIcon>
      )}

      {/* YT Music match badge */}
      <YtMusicBadge match={track.ytmusic} playlistId={playlistId} trackId={track.track_id} track={track} />

      {/* Remove track — pale-red text, low emphasis */}
      <Button variant="subtle" color="red" size="xs" onClick={() => onRemove(track)}>
        {t('playlists.detail.remove_track_cta')}
      </Button>
    </Group>
  );
}

/** Sortable wrapper: the dragged tile is shown via DragOverlay (see the list),
 *  so the in-list tile just fades to a placeholder while dragging. */
// No layout animation on reorder: the drop is instant in both directions
// (the dragged tile would otherwise slide in from its old slot — visible as a
// "jump from above" when moving a track up). Items still shift smoothly while
// dragging — that is the strategy transform, not a layout change.
const noLayoutAnimation: AnimateLayoutChanges = () => false;

export function PlaylistTrackRow(props: PlaylistTrackRowProps) {
  const { track, reorderDisabled = false } = props;
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: track.track_id,
    animateLayoutChanges: noLayoutAnimation,
  });
  const rootStyle: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
    borderRadius: 'var(--mantine-radius-md)',
  };
  const handleProps = reorderDisabled
    ? undefined
    : ({ ...attributes, ...listeners } as HTMLAttributes<HTMLButtonElement>);

  return (
    <PlaylistTrackRowView
      {...props}
      rootRef={setNodeRef}
      rootStyle={rootStyle}
      handleProps={handleProps}
    />
  );
}
