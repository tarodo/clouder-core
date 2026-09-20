import { Button, Container, Divider, Group, Stack, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../auth/useAuth';
import { IconLogout } from '../components/icons';
import { MyStylesSection } from '../features/profile/components/MyStylesSection';

export function ProfilePage() {
  const { t } = useTranslation();
  const { signOut, state } = useAuth();
  const name = state.status === 'authenticated' ? state.user.display_name : '';

  return (
    <Container size="sm" py="xl">
      <Stack gap="lg">
        <Group justify="space-between" align="center">
          <div>
            <Title order={2}>{t('appshell.profile')}</Title>
            <Text c="dimmed">{t('user_menu.signed_in_as', { name })}</Text>
          </div>
          <Button
            leftSection={<IconLogout size={16} />}
            variant="default"
            onClick={() => {
              void signOut();
            }}
          >
            {t('user_menu.sign_out')}
          </Button>
        </Group>

        <Divider />

        <MyStylesSection />
      </Stack>
    </Container>
  );
}
