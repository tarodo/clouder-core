import { Menu, Button } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../auth/useAuth';
import { IconLogout, IconUser } from './icons';

export function UserMenu() {
  const { state, signOut } = useAuth();
  const { t } = useTranslation();

  if (state.status !== 'authenticated') return null;

  return (
    <Menu position="bottom-end" withArrow>
      <Menu.Target>
        <Button variant="subtle" leftSection={<IconUser size={16} />}>
          {state.user.display_name}
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>{t('user_menu.signed_in_as', { name: state.user.display_name })}</Menu.Label>
        <Menu.Item
          leftSection={<IconLogout size={16} />}
          onClick={() => {
            void signOut();
          }}
        >
          {t('user_menu.sign_out')}
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
