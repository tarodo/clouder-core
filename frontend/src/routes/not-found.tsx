import { Button, Center, Stack, Text, Title } from '@mantine/core';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';

export function NotFoundPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
    <Center mih="100vh" p="xl">
      <Stack align="center" gap="md" maw={420}>
        <Title order={2}>{t('router.not_found_title')}</Title>
        <Text c="dimmed" ta="center">
          {t('router.not_found_body')}
        </Text>
        <Button onClick={() => navigate('/')}>{t('empty_state.back_home')}</Button>
      </Stack>
    </Center>
  );
}
