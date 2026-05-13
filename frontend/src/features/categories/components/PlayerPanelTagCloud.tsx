import { useMemo } from 'react';
import { Chip, Group, Stack, Text } from '@mantine/core';
import { useTags } from '../../tags';

export interface PlayerPanelTagCloudProps {
  trackId: string;
  assignedTagIds: readonly string[];
  onAdd: (tagId: string) => void;
  onRemove: (tagId: string) => void;
}

export function PlayerPanelTagCloud(props: PlayerPanelTagCloudProps) {
  const { assignedTagIds, onAdd, onRemove } = props;
  const tagsQuery = useTags();
  const assigned = useMemo(() => new Set(assignedTagIds), [assignedTagIds]);

  const tags = useMemo(
    () =>
      (tagsQuery.data ?? [])
        .slice()
        .sort((a, b) => a.name.localeCompare(b.name)),
    [tagsQuery.data],
  );

  if (tags.length === 0) {
    return (
      <Text c="dimmed" size="sm">
        No tags yet
      </Text>
    );
  }

  return (
    <Stack gap="xs">
      <Group gap="xs" wrap="wrap">
        {tags.map((t) => {
          const selected = assigned.has(t.id);
          return (
            <Chip
              key={t.id}
              checked={selected}
              size="sm"
              variant={selected ? 'filled' : 'outline'}
              color={t.color ?? 'gray'}
              onChange={() => (selected ? onRemove(t.id) : onAdd(t.id))}
            >
              {t.name}
            </Chip>
          );
        })}
      </Group>
    </Stack>
  );
}
