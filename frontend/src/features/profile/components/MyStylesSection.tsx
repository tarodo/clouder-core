import { useEffect, useMemo, useState } from 'react';
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
  arrayMove,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { ActionIcon, Group, Loader, Stack, Text, TextInput, Title } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useAllStyles, type CatalogStyle } from '../../../hooks/useAllStyles';
import { useUpdateMyStyles } from '../../../hooks/useUpdateMyStyles';
import { SelectedStyleRow, SelectedStyleRowView } from './SelectedStyleRow';

export function MyStylesSection() {
  const { t } = useTranslation();
  const { data, dataUpdatedAt, isLoading } = useAllStyles();
  const { queueSelection } = useUpdateMyStyles();
  const [draft, setDraft] = useState<string[] | null>(null);
  const [search, setSearch] = useState('');
  const [dragId, setDragId] = useState<string | null>(null);

  const items = useMemo(() => data?.items ?? [], [data]);
  const byId = useMemo(
    () => new Map(items.map((s) => [s.id, s])),
    [items],
  );

  // `draft` holds the optimistic order until a fresh fetch lands — success or
  // failure. Without this, a failed PUT (useUpdateMyStyles still invalidates on
  // error) would leave the UI showing the unsaved selection forever, and any
  // later edit would build on that wrong baseline instead of on server truth.
  // Keyed on `dataUpdatedAt` rather than `data` itself: react-query's default
  // structural sharing keeps the same `data` reference when a refetch resolves
  // with content deep-equal to what's cached (exactly the failed-PUT case,
  // where the server never changed), so a `[data]` dependency would never fire.
  useEffect(() => {
    setDraft(null);
  }, [dataUpdatedAt]);

  const selectedIds = useMemo(() => {
    if (draft) return draft;
    return items
      .filter((s) => s.selected)
      .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
      .map((s) => s.id);
  }, [draft, items]);

  const selected = selectedIds
    .map((id) => byId.get(id))
    .filter((s): s is CatalogStyle => Boolean(s));

  const addable = items.filter(
    (s) =>
      !selectedIds.includes(s.id) &&
      s.name.toLowerCase().includes(search.trim().toLowerCase()),
  );

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  function commit(next: string[]) {
    setDraft(next);
    queueSelection(next);
  }

  function onDragEnd(event: DragEndEvent) {
    setDragId(null);
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = selectedIds.indexOf(String(active.id));
    const newIndex = selectedIds.indexOf(String(over.id));
    if (oldIndex === -1 || newIndex === -1) return;
    commit(arrayMove(selectedIds, oldIndex, newIndex));
  }

  if (isLoading) return <Loader size="sm" />;

  const dragged = dragId ? byId.get(dragId) : undefined;

  return (
    <Stack gap="md">
      <div>
        <Title order={4}>{t('profile.styles.title')}</Title>
        <Text size="sm" c="dimmed">
          {t('profile.styles.description')}
        </Text>
      </div>

      {selected.length === 0 ? (
        <Text size="sm" c="dimmed">
          {t('profile.styles.empty_hint')}
        </Text>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={(e: DragStartEvent) => setDragId(String(e.active.id))}
          onDragEnd={onDragEnd}
          onDragCancel={() => setDragId(null)}
        >
          <SortableContext items={selectedIds} strategy={verticalListSortingStrategy}>
            <Stack gap="xs">
              {selected.map((s) => (
                <SelectedStyleRow
                  key={s.id}
                  style={s}
                  onRemove={(id) => commit(selectedIds.filter((x) => x !== id))}
                />
              ))}
            </Stack>
          </SortableContext>
          <DragOverlay dropAnimation={null}>
            {dragged ? (
              <SelectedStyleRowView style={dragged} onRemove={() => undefined} overlay />
            ) : null}
          </DragOverlay>
        </DndContext>
      )}

      <div>
        <Title order={5}>{t('profile.styles.add_title')}</Title>
        <TextInput
          mt="xs"
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          placeholder={t('profile.styles.add_placeholder')}
        />
        <Stack gap={4} mt="xs">
          {addable.map((s) => (
            <Group key={s.id} justify="space-between" wrap="nowrap">
              <Text size="sm">{s.name}</Text>
              <ActionIcon
                variant="subtle"
                aria-label={`add ${s.name}`}
                onClick={() => commit([...selectedIds, s.id])}
              >
                <IconPlus size={16} />
              </ActionIcon>
            </Group>
          ))}
        </Stack>
      </div>
    </Stack>
  );
}
