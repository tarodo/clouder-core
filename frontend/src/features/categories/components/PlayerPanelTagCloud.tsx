import { useMemo, useState } from 'react';
import { ActionIcon, Chip, Group, Stack, Text } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useTags, TrackTagsPopover } from '../../tags';
import { softTagColors } from '../../tags/lib/tagPalette';

export interface PlayerPanelTagCloudProps {
  categoryId: string;
  trackId: string;
  assignedTagIds: readonly string[];
  onAdd: (tagId: string) => void;
  onRemove: (tagId: string) => void;
}

export function PlayerPanelTagCloud(props: PlayerPanelTagCloudProps) {
  const { categoryId, trackId, assignedTagIds, onAdd, onRemove } = props;
  const { t } = useTranslation();
  const tagsQuery = useTags();
  const [opened, setOpened] = useState(false);
  const assigned = useMemo(() => new Set(assignedTagIds), [assignedTagIds]);

  const tags = useMemo(
    () => (tagsQuery.data ?? []).slice().sort((a, b) => a.name.localeCompare(b.name)),
    [tagsQuery.data],
  );

  const addButton = (
    <ActionIcon
      variant="subtle"
      size="sm"
      aria-label={t('tags.cell.add_aria')}
      onClick={() => setOpened((o) => !o)}
    >
      <IconPlus size={14} />
    </ActionIcon>
  );

  return (
    <Stack gap="xs">
      <Group gap="xs" wrap="wrap" align="center">
        {tags.map((tg) => {
          const selected = assigned.has(tg.id);
          const sc = softTagColors(tg.color);
          return (
            <Chip
              key={tg.id}
              checked={selected}
              size="sm"
              variant="outline"
              onChange={() => (selected ? onRemove(tg.id) : onAdd(tg.id))}
              styles={{
                label: selected
                  ? {
                      backgroundColor: sc.bg,
                      color: sc.fg,
                      border: `1px solid ${sc.border}`,
                    }
                  : {
                      backgroundColor: 'transparent',
                      color: 'var(--mantine-color-dimmed)',
                      border: '1px solid var(--mantine-color-default-border)',
                    },
                iconWrapper: { display: 'none' },
              }}
            >
              {tg.name}
            </Chip>
          );
        })}
        {tags.length === 0 && (
          <Text c="dimmed" size="sm">
            No tags yet
          </Text>
        )}
        <TrackTagsPopover
          opened={opened}
          onClose={() => setOpened(false)}
          target={addButton}
          categoryId={categoryId}
          trackId={trackId}
          currentTagIds={assignedTagIds}
        />
      </Group>
    </Stack>
  );
}
