import { useMemo, useState } from 'react';
import { Stack } from '@mantine/core';
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  arrayMove,
} from '@dnd-kit/sortable';
import type { PlaylistTrack } from '../lib/playlistTypes';
import { PlaylistTrackRow, PlaylistTrackRowView } from './PlaylistTrackRow';

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
  const [activeId, setActiveId] = useState<string | null>(null);

  function onDragStart(event: DragStartEvent) {
    if (reorderDisabled) return;
    setActiveId(String(event.active.id));
  }

  function onDragEnd(event: DragEndEvent) {
    setActiveId(null);
    if (reorderDisabled) return;
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = ids.indexOf(String(active.id));
    const newIndex = ids.indexOf(String(over.id));
    if (oldIndex === -1 || newIndex === -1) return;
    onReorder(arrayMove(ids, oldIndex, newIndex));
  }

  const activeIndex = activeId ? ids.indexOf(activeId) : -1;
  const activeTrack = activeIndex >= 0 ? tracks[activeIndex] : null;

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragCancel={() => setActiveId(null)}
    >
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
      {/* The dragged tile lives in its own layer: immune to list re-renders
          (e.g. playback ticks) so the drop animates smoothly instead of
          snapping. */}
      <DragOverlay>
        {activeTrack ? (
          <PlaylistTrackRowView
            track={activeTrack}
            position={activeIndex + 1}
            onRemove={() => {}}
            onPlay={onPlayTrack ? () => {} : undefined}
            isCurrent={activeTrack.track_id === currentTrackId}
            overlay
          />
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}
