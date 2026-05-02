import { useMemo } from 'react';
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
import { Stack } from '@mantine/core';
import type { Category } from '../hooks/useCategoriesByStyle';
import { CategoryRow } from './CategoryRow';

export interface CategoriesListProps {
  categories: Category[];
  onReorder: (orderedIds: string[]) => void;
  onRename: (c: Category) => void;
  onDelete: (c: Category) => void;
}

export function CategoriesList({ categories, onReorder, onRename, onDelete }: CategoriesListProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const ids = useMemo(() => categories.map((c) => c.id), [categories]);

  function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = ids.indexOf(String(active.id));
    const newIndex = ids.indexOf(String(over.id));
    if (oldIndex === -1 || newIndex === -1) return;
    const next = arrayMove(ids, oldIndex, newIndex);
    onReorder(next);
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        <Stack gap="xs">
          {categories.map((c) => (
            <CategoryRow key={c.id} category={c} onRename={onRename} onDelete={onDelete} />
          ))}
        </Stack>
      </SortableContext>
    </DndContext>
  );
}
