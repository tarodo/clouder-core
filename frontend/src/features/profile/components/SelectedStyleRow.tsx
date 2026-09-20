import type { CSSProperties, HTMLAttributes } from 'react';
import { useSortable, type AnimateLayoutChanges } from '@dnd-kit/sortable';
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

interface ViewProps extends SelectedStyleRowProps {
  /** Sortable node ref + transform style (omitted for the drag-overlay clone). */
  rootRef?: (el: HTMLElement | null) => void;
  rootStyle?: CSSProperties;
  /** Drag-handle listeners/attributes (omitted for the overlay clone). */
  handleProps?: HTMLAttributes<HTMLButtonElement>;
}

/**
 * Presentational row. Shared by the sortable row and the DragOverlay clone so
 * the dragged tile is visually identical while living in its own layer — and,
 * crucially, so the clone never calls useSortable itself (see SelectedStyleRow
 * below): two live useSortable registrations for the same id inside one
 * DndContext would corrupt dnd-kit's node-ref registry mid-drag.
 */
export function SelectedStyleRowView({
  style,
  onRemove,
  overlay = false,
  rootRef,
  rootStyle,
  handleProps,
}: ViewProps) {
  const { t } = useTranslation();
  const paperStyle: CSSProperties = overlay
    ? { ...rootStyle, boxShadow: 'var(--mantine-shadow-md)', cursor: 'grabbing' }
    : rootStyle ?? {};

  return (
    <Paper ref={rootRef} withBorder p="xs" style={paperStyle}>
      <Group justify="space-between" wrap="nowrap">
        <Group gap="xs" wrap="nowrap">
          <ActionIcon
            variant="subtle"
            aria-label={t('profile.styles.drag_handle')}
            {...handleProps}
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

// No layout animation on reorder: matches PlaylistTrackRow's sortable wrapper.
const noLayoutAnimation: AnimateLayoutChanges = () => false;

/** Sortable wrapper for the real list row. The dragged tile is rendered via
 *  DragOverlay using SelectedStyleRowView directly (see MyStylesSection), so
 *  this wrapper — and its useSortable call — is never mounted for the overlay
 *  clone. Only one useSortable registration per id is ever live at a time. */
export function SelectedStyleRow(props: SelectedStyleRowProps) {
  const { style } = props;
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: style.id,
    animateLayoutChanges: noLayoutAnimation,
  });
  const rootStyle: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0 : 1,
  };
  const handleProps = { ...attributes, ...listeners } as HTMLAttributes<HTMLButtonElement>;

  return (
    <SelectedStyleRowView
      {...props}
      rootRef={setNodeRef}
      rootStyle={rootStyle}
      handleProps={handleProps}
    />
  );
}
