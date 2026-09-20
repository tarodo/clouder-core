import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { ActionIcon, Group, Paper, Text } from '@mantine/core';
import { IconGripVertical, IconX } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { CatalogStyle } from '../../../hooks/useAllStyles';

export interface SelectedStyleRowProps {
  style: CatalogStyle;
  onRemove: (styleId: string) => void;
  /** True when rendered inside the DragOverlay. */
  overlay?: boolean;
}

export function SelectedStyleRow({ style, onRemove, overlay }: SelectedStyleRowProps) {
  const { t } = useTranslation();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: style.id, animateLayoutChanges: () => false });

  return (
    <Paper
      ref={overlay ? undefined : setNodeRef}
      withBorder
      p="xs"
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: !overlay && isDragging ? 0 : 1,
      }}
    >
      <Group justify="space-between" wrap="nowrap">
        <Group gap="xs" wrap="nowrap">
          <ActionIcon
            variant="subtle"
            aria-label={t('profile.styles.drag_handle')}
            {...attributes}
            {...listeners}
          >
            <IconGripVertical size={16} />
          </ActionIcon>
          <Text>{style.name}</Text>
        </Group>
        <ActionIcon
          variant="subtle"
          color="red"
          aria-label={`remove ${style.name}`}
          title={t('profile.styles.remove')}
          onClick={() => onRemove(style.id)}
        >
          <IconX size={16} />
        </ActionIcon>
      </Group>
    </Paper>
  );
}
