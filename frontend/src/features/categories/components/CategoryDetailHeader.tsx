import { Button, Group, Stack, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export interface CategoryDetailHeaderProps {
  name: string;
  trackCountLabel: string;
  onRename: () => void;
  onDelete: () => void;
}

/**
 * Category detail header: the category name with its Rename/Delete actions
 * placed directly after it (so the buttons' purpose is obvious) and vertically
 * centered to the title. The track count sits on the line below the name.
 */
export function CategoryDetailHeader({
  name,
  trackCountLabel,
  onRename,
  onDelete,
}: CategoryDetailHeaderProps) {
  const { t } = useTranslation();
  return (
    <Stack gap={2}>
      <Group gap="sm" align="center" wrap="wrap">
        <Title order={1}>{name}</Title>
        <Button variant="default" onClick={onRename}>
          {t('categories.detail.actions.rename')}
        </Button>
        <Button color="red" variant="light" onClick={onDelete}>
          {t('categories.detail.actions.delete')}
        </Button>
      </Group>
      <Text c="dimmed">{trackCountLabel}</Text>
    </Stack>
  );
}
