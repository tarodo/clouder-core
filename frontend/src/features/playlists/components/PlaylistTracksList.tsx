import { useMemo } from 'react';
import { Stack } from '@mantine/core';
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  arrayMove,
} from '@dnd-kit/sortable';
import type { PlaylistTrack } from '../lib/playlistTypes';
import { PlaylistTrackRow } from './PlaylistTrackRow';

export interface PlaylistTracksListProps {
  tracks: PlaylistTrack[];
  onReorder: (orderedIds: string[]) => void;
  onRemove: (track: PlaylistTrack) => void;
  reorderDisabled?: boolean;
  /** Called when the user clicks play on a track row. */
  onPlayTrack?: (track: PlaylistTrack) => void;
  /** track_id of the currently playing track for highlight. */
  currentTrackId?: string | null;
  /** Called when a tag is removed (by clicking its pill) on a track row. */
  onRemoveTag?: (track: PlaylistTrack, tagId: string) => void;
}

export function PlaylistTracksList({
  tracks,
  onReorder,
  onRemove,
  reorderDisabled = false,
  onPlayTrack,
  currentTrackId,
  onRemoveTag,
}: PlaylistTracksListProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const ids = useMemo(() => tracks.map((t) => t.track_id), [tracks]);

  function onDragEnd(event: DragEndEvent) {
    if (reorderDisabled) return;
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = ids.indexOf(String(active.id));
    const newIndex = ids.indexOf(String(over.id));
    if (oldIndex === -1 || newIndex === -1) return;
    onReorder(arrayMove(ids, oldIndex, newIndex));
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        <Stack gap="xs">
          {tracks.map((t, i) => (
            <PlaylistTrackRow
              key={t.track_id}
              track={t}
              position={i + 1}
              onRemove={onRemove}
              reorderDisabled={reorderDisabled}
              onPlay={onPlayTrack ? () => onPlayTrack(t) : undefined}
              isCurrent={t.track_id === currentTrackId}
              onRemoveTag={onRemoveTag ? (tagId) => onRemoveTag(t, tagId) : undefined}
            />
          ))}
        </Stack>
      </SortableContext>
    </DndContext>
  );
}
