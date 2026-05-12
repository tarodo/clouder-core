import { ActionIcon, Group, Text } from '@mantine/core';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { IconExternalLink, IconGripVertical } from '@tabler/icons-react';
import type { PlaylistTrack } from '../lib/playlistTypes';
import { OriginBadge } from './OriginBadge';
import { PlaylistTrackRowActions } from './PlaylistTrackRowActions';

export interface PlaylistTrackRowProps {
  track: PlaylistTrack;
  position: number;
  onRemove: (track: PlaylistTrack) => void;
  reorderDisabled?: boolean;
}

function formatDuration(ms: number | null): string {
  if (!ms || ms <= 0) return '';
  const total = Math.round(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function PlaylistTrackRow({
  track,
  position,
  onRemove,
  reorderDisabled = false,
}: PlaylistTrackRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: track.track_id,
  });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    borderRadius: 'var(--mantine-radius-md)',
  };

  return (
    <Group
      ref={setNodeRef}
      style={style}
      gap="sm"
      wrap="nowrap"
      p="sm"
      bg="var(--color-bg-elevated)"
      bd="1px solid var(--color-border)"
    >
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
      <Text fw={500} size="sm" style={{ minWidth: 32 }}>
        {position}.
      </Text>
      <Text flex={1} truncate>
        {track.title}
      </Text>
      <Text c="dimmed" size="sm">
        {formatDuration(track.length_ms)}
      </Text>
      <OriginBadge origin={track.origin} />
      {track.spotify_id ? (
        <ActionIcon
          component="a"
          href={`https://open.spotify.com/track/${track.spotify_id}`}
          target="_blank"
          rel="noopener noreferrer"
          variant="subtle"
          aria-label="Open in Spotify"
        >
          <IconExternalLink size={16} />
        </ActionIcon>
      ) : null}
      <PlaylistTrackRowActions onRemove={() => onRemove(track)} />
    </Group>
  );
}
