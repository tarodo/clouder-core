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
}

export function PlaylistTracksList({ tracks, onReorder, onRemove }: PlaylistTracksListProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const ids = useMemo(() => tracks.map((t) => t.track_id), [tracks]);

  function onDragEnd(event: DragEndEvent) {
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
            />
          ))}
        </Stack>
      </SortableContext>
    </DndContext>
  );
}
