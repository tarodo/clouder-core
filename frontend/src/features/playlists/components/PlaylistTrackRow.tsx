import { useState } from 'react';
import { ActionIcon, Button, Group, Stack, Text, Tooltip } from '@mantine/core';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import {
  IconExternalLink,
  IconGripVertical,
  IconPlayerPlayFilled,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { PlaylistTrack, PlaylistTrackTag } from '../lib/playlistTypes';
import { formatLength, formatReleaseDate } from '../../../lib/formatters';
import { TagPill, TrackTagsPopover } from '../../tags';

export interface PlaylistTrackRowProps {
  track: PlaylistTrack;
  position: number;
  onRemove: (track: PlaylistTrack) => void;
  reorderDisabled?: boolean;
  onPlay?: () => void;
  isCurrent?: boolean;
  onAddTag?: (tag: PlaylistTrackTag) => void;
  onRemoveTag?: (tagId: string) => void;
}

export function PlaylistTrackRow({
  track,
  position,
  onRemove,
  reorderDisabled = false,
  onPlay,
  isCurrent,
  onAddTag,
  onRemoveTag,
}: PlaylistTrackRowProps) {
  const { t } = useTranslation();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: track.track_id,
  });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    borderRadius: 'var(--mantine-radius-md)',
  };

  const [popoverOpen, setPopoverOpen] = useState(false);

  const canPlay = !!onPlay && !!track.spotify_id;
  const artistNames = track.artists.map((a) => a.name).join(', ');

  return (
    <Group
      ref={setNodeRef}
      style={style}
      data-current={isCurrent ? 'true' : undefined}
      gap="sm"
      wrap="nowrap"
      p="sm"
      bg={isCurrent ? 'var(--mantine-color-default-hover)' : 'var(--color-bg-elevated)'}
      bd="1px solid var(--color-border)"
    >
      {/* Drag handle */}
      <ActionIcon
        variant="subtle"
        aria-label="Drag handle"
        disabled={reorderDisabled}
        {...(reorderDisabled ? {} : attributes)}
        {...(reorderDisabled ? {} : listeners)}
        aria-roledescription="sortable"
        style={{ cursor: reorderDisabled ? 'not-allowed' : 'grab', touchAction: 'none' }}
      >
        <IconGripVertical size={18} />
      </ActionIcon>

      {/* Position number */}
      <Text fw={500} size="sm" style={{ minWidth: 32 }}>
        {position}.
      </Text>

      {/* Play button (only when the page wires playback) */}
      {onPlay !== undefined && (
        <Tooltip
          label={
            track.spotify_id
              ? t('categories.tracks_table.play_aria')
              : t('categories.tracks_table.play_unavailable')
          }
        >
          <ActionIcon
            variant="subtle"
            size="md"
            disabled={!canPlay}
            onClick={canPlay ? onPlay : undefined}
            aria-label={t('categories.tracks_table.play_aria')}
          >
            <IconPlayerPlayFilled size={16} />
          </ActionIcon>
        </Tooltip>
      )}

      {/* Track info */}
      <Stack gap={2} flex={1} style={{ minWidth: 0 }}>
        <Group gap="xs" wrap="nowrap">
          <Text fw={500} truncate>
            {track.title}
          </Text>
          {track.mix_name && (
            <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
              {track.mix_name}
            </Text>
          )}
        </Group>
        {artistNames && (
          <Text size="sm" truncate>
            {artistNames}
          </Text>
        )}
        <Group gap="xs" wrap="wrap">
          <Text size="xs" c="dimmed">
            {track.label?.name ?? '—'}
          </Text>
          {track.bpm != null && (
            <Text size="xs" c="dimmed" className="font-mono">
              {track.bpm}
            </Text>
          )}
          <Text size="xs" c="dimmed" className="font-mono">
            {formatLength(track.length_ms)}
          </Text>
          <Text size="xs" c="dimmed" className="font-mono">
            {formatReleaseDate(track.spotify_release_date)}
          </Text>
        </Group>

        {/* Editable tags */}
        <Group gap={4} wrap="wrap" mt={2}>
          {track.tags.map((tag) => (
            <TagPill
              key={tag.id}
              name={tag.name}
              color={tag.color}
              onRemove={onRemoveTag ? () => onRemoveTag(tag.id) : undefined}
            />
          ))}
          <TrackTagsPopover
            opened={popoverOpen}
            onClose={() => setPopoverOpen(false)}
            target={
              <ActionIcon
                variant="subtle"
                size="xs"
                aria-label={t('tags.cell.add_aria')}
                onClick={() => setPopoverOpen((o) => !o)}
              >
                +
              </ActionIcon>
            }
            trackId={track.track_id}
            currentTagIds={track.tags.map((t) => t.id)}
            onToggle={(tag, checked) => {
              if (checked) {
                onAddTag?.(tag);
              } else {
                onRemoveTag?.(tag.id);
              }
            }}
          />
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
          aria-label={t('playlists.publish.open_in_spotify')}
        >
          <IconExternalLink size={16} />
        </ActionIcon>
      )}

      {/* Remove button */}
      <Button
        color="red"
        variant="light"
        size="xs"
        onClick={() => onRemove(track)}
      >
        {t('playlists.detail.remove_track_cta')}
      </Button>
    </Group>
  );
}
