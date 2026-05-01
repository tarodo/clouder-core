import { Button, Center, Stack, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../auth/useAuth';
import { IconLogout } from '../components/icons';

export function ProfilePage() {
  const { t } = useTranslation();
  const { signOut, state } = useAuth();
  const name = state.status === 'authenticated' ? state.user.display_name : '';

  return (
    <Center mih="60vh" p="xl">
      <Stack align="center" gap="md" maw={420}>
        <Title order={2}>{t('appshell.profile')}</Title>
        <Text c="dimmed">{t('user_menu.signed_in_as', { name })}</Text>
        <Button
          leftSection={<IconLogout size={16} />}
          variant="default"
          onClick={() => {
            void signOut();
          }}
        >
          {t('user_menu.sign_out')}
        </Button>
      </Stack>
    </Center>
  );
}
