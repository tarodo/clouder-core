import { ActionIcon, Menu } from '@mantine/core';
import { IconDotsVertical } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

export interface PlaylistTrackRowActionsProps {
  onRemove: () => void;
}

export function PlaylistTrackRowActions({ onRemove }: PlaylistTrackRowActionsProps) {
  const { t } = useTranslation();
  return (
    <Menu withinPortal={false} transitionProps={{ duration: 0 }}>
      <Menu.Target>
        <ActionIcon variant="subtle" aria-label="Track actions">
          <IconDotsVertical size={16} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item color="red" onClick={onRemove}>
          {t('categories.row_actions.remove_label')}
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
