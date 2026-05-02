import { ActionIcon, Badge, Group, Menu, Text } from '@mantine/core';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { IconDotsVertical, IconGripVertical } from '@tabler/icons-react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { Category } from '../hooks/useCategoriesByStyle';

export interface CategoryRowProps {
  category: Category;
  onRename: (c: Category) => void;
  onDelete: (c: Category) => void;
}

export function CategoryRow({ category, onRename, onDelete }: CategoryRowProps) {
  const { t } = useTranslation();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: category.id,
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
        {...attributes}
        {...listeners}
        aria-roledescription="sortable"
        style={{ cursor: 'grab', touchAction: 'none' }}
      >
        <IconGripVertical size={18} />
      </ActionIcon>
      <Text
        component={Link}
        to={`/categories/${category.style_id}/${category.id}`}
        fw={500}
        flex={1}
        c="var(--color-fg)"
        td="none"
      >
        {category.name}
      </Text>
      <Badge variant="default" size="sm">
        {t('categories.track_count', { count: category.track_count })}
      </Badge>
      <Menu withinPortal={false} transitionProps={{ duration: 0 }}>
        <Menu.Target>
          <ActionIcon variant="subtle" aria-label="Actions">
            <IconDotsVertical size={18} />
          </ActionIcon>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item onClick={() => onRename(category)}>{t('categories.row_menu.rename')}</Menu.Item>
          <Menu.Item color="red" onClick={() => onDelete(category)}>
            {t('categories.row_menu.delete')}
          </Menu.Item>
        </Menu.Dropdown>
      </Menu>
    </Group>
  );
}
