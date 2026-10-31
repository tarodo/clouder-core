import { Button, Group, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export interface CategoryDetailHeaderProps {
  name: string;
  trackCountLabel: string;
  onRename: () => void;
  onDelete: () => void;
}

/**
 * Category detail header, one row: the category name with its Rename/Delete actions placed
 * directly after it (so the buttons' purpose is obvious), then the track count.
 */
export function CategoryDetailHeader({
  name,
  trackCountLabel,
  onRename,
  onDelete,
}: CategoryDetailHeaderProps) {
  const { t } = useTranslation();
  return (
    <Group gap="sm" align="center" wrap="wrap">
      <Title order={1}>{name}</Title>
      <Button variant="default" onClick={onRename}>
        {t('categories.detail.actions.rename')}
      </Button>
      <Button color="red" variant="light" onClick={onDelete}>
        {t('categories.detail.actions.delete')}
      </Button>
      <Text c="dimmed">{trackCountLabel}</Text>
    </Group>
  );
}
