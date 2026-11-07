import type { CSSProperties, HTMLAttributes } from 'react';
import { ActionIcon, Button, Group, Menu, Stack, Text, Tooltip } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { useSortable, type AnimateLayoutChanges } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import {
  IconBrandSpotify,
  IconBrandYoutube,
  IconDotsVertical,
  IconGripVertical,
  IconLink,
  IconMessageCircle,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { PlaylistTrack } from '../lib/playlistTypes';
import { beatportTrackUrl } from '../lib/playlistExport';
import { formatCommentCount, formatLength, formatReleaseDate } from '../../../lib/formatters';
import { TagPill } from '../../tags';
import { YtMusicBadge } from './YtMusicBadge';
import { TrackKey } from '../../playback/TrackKey';
import { PlayPauseButton } from '../../playback/PlayPauseButton';
import { AiBadge } from '../../playback/AiBadge';
import { AiRepBadge, NameLine, NamesWithAi } from '../../library/components/AiRepBadge';

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
  // phone: title, artists and tags get the width; links and Remove go behind ⋮
  const isMobile = useMediaQuery('(max-width: 64em)');
  const canPlay = !!onPlay && !!track.spotify_id;
  const artistNames = track.artists.map((a) => a.name).join(', ');
  const spotifyUrl = track.spotify_id ? `https://open.spotify.com/track/${track.spotify_id}` : null;
  const beatportUrl = track.beatport_track_id
    ? beatportTrackUrl(track.beatport_track_id, track.beatport_slug)
    : null;
  const yt = track.ytmusic;
  const ytUrl = yt?.status === 'matched' ? yt.url : null;
  const tags = track.tags.map((tag) => <TagPill key={tag.id} name={tag.name} color={tag.color} />);
  const groupStyle: CSSProperties = overlay
    ? { ...rootStyle, boxShadow: 'var(--mantine-shadow-md)', cursor: 'grabbing' }
    : (rootStyle ?? {});

  return (
    <Group
      ref={rootRef}
      style={groupStyle}
      data-current={isCurrent ? 'true' : undefined}
      gap={isMobile ? 6 : 'sm'}
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
      <Text fw={500} size="sm" style={{ minWidth: isMobile ? 22 : 32 }}>
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

      {isMobile ? (
        <>
          <Stack gap={2} flex={1} style={{ minWidth: 0 }}>
            <Group gap={4} wrap="nowrap" align="flex-start">
              <Text fw={500} size="sm" lineClamp={2}>
                <span>{track.title}</span>
                {track.mix_name && (
                  <Text span size="xs" c="dimmed">
                    {' '}
                    {track.mix_name}
                  </Text>
                )}
              </Text>
              <AiBadge verdict={track.ai_verdict} />
            </Group>
            {artistNames && (
              <Text size="xs" c="dimmed" lineClamp={2}>
                <NamesWithAi items={track.artists} />
              </Text>
            )}
            {tags.length > 0 && (
              <Group gap={4} wrap="wrap">
                {tags}
              </Group>
            )}
          </Stack>

          {/* A match to review is a task, not a link: it stays in the row */}
          {(yt?.status === 'needs_review' || yt?.status === 'not_found') && (
            <YtMusicBadge
              match={yt}
              playlistId={playlistId}
              trackId={track.track_id}
              track={track}
            />
          )}

          <Menu position="bottom-end" withinPortal>
            <Menu.Target>
              <ActionIcon
                variant="subtle"
                color="gray"
                aria-label={t('categories.row_actions.trigger_aria')}
              >
                <IconDotsVertical size={16} />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              {spotifyUrl && (
                <Menu.Item
                  component="a"
                  href={spotifyUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  leftSection={<IconBrandSpotify size={14} />}
                >
                  {t('playlists.publish.open_in_spotify')}
                </Menu.Item>
              )}
              {beatportUrl && (
                <Menu.Item
                  component="a"
                  href={beatportUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  leftSection={<IconLink size={14} />}
                >
                  {t('playlists.detail.open_beatport')}
                </Menu.Item>
              )}
              {ytUrl && (
                <Menu.Item
                  component="a"
                  href={ytUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  leftSection={<IconBrandYoutube size={14} />}
                >
                  {t('playlists.ytmusic.openOnYt', 'Open on YT Music')}
                </Menu.Item>
              )}
              {(spotifyUrl || beatportUrl || ytUrl) && <Menu.Divider />}
              <Menu.Item color="red" onClick={() => onRemove(track)}>
                {t('playlists.detail.remove_track_cta')}
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </>
      ) : (
        <>
          {/* Track info — two lines: title/mix/artists, then meta + editable tags */}
          <Stack gap={2} flex={1} style={{ minWidth: 0 }}>
            <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
              <Text fw={500} truncate>
                {track.title}
              </Text>
              <AiBadge verdict={track.ai_verdict} />
              {track.mix_name && (
                <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                  {track.mix_name}
                </Text>
              )}
              {artistNames && (
                <NameLine size="sm" c="dimmed">
                  <NamesWithAi items={track.artists} />
                </NameLine>
              )}
            </Group>
            <Group gap="xs" wrap="wrap" align="center">
              <TrackKey camelot={track.key_camelot} name={track.key_name} size="xs" />
              <Text size="xs" c="dimmed">
                {track.label?.name ?? '—'}
                <AiRepBadge rep={track.label?.ai} ml={4} />
                {[
                  '',
                  track.bpm != null ? `${track.bpm} BPM` : null,
                  // formatLength/formatReleaseDate return '—' for null, so guard
                  // here to truly omit missing parts (no "| — | —" gaps).
                  track.length_ms ? formatLength(track.length_ms) : null,
                  track.spotify_release_date ? formatReleaseDate(track.spotify_release_date) : null,
                ]
                  .filter((part, i) => i === 0 || part)
                  .join(' | ')}
              </Text>
              {track.comment_count != null && (
                <Tooltip label={t('categories.tracks_table.comments_hint')} withArrow>
                  <Group
                    gap={2}
                    wrap="nowrap"
                    c="dimmed"
                    aria-label={t('categories.tracks_table.comments_hint')}
                  >
                    <IconMessageCircle size={12} />
                    <Text size="xs" className="font-mono">
                      {formatCommentCount(track.comment_count)}
                    </Text>
                  </Group>
                </Tooltip>
              )}
              {/* Read-only in the list — tags are edited in the player. */}
              {tags}
            </Group>
          </Stack>

          {/* Spotify external link */}
          {spotifyUrl && (
            <ActionIcon
              component="a"
              href={spotifyUrl}
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
          {beatportUrl && (
            <ActionIcon
              component="a"
              href={beatportUrl}
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
          <YtMusicBadge
            match={track.ytmusic}
            playlistId={playlistId}
            trackId={track.track_id}
            track={track}
          />

          {/* Remove track — pale-red text, low emphasis */}
          <Button variant="subtle" color="red" size="xs" onClick={() => onRemove(track)}>
            {t('playlists.detail.remove_track_cta')}
          </Button>
        </>
      )}
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
