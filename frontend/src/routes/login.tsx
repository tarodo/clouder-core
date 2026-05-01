import { Button, Center, Stack, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router';

export function LoginPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const errorCode = params.get('error');

  let banner: { title: string; body: string } | null = null;
  if (errorCode === 'premium_required') {
    banner = { title: t('auth.premium_required'), body: t('auth.premium_body') };
  } else if (errorCode) {
    banner = { title: t('auth.oauth_failed'), body: t('auth.oauth_failed_body') };
  }

  const onSignIn = () => {
    window.location.href = '/auth/login';
  };

  return (
    <Center mih="100vh" p="xl">
      <Stack align="center" gap="lg" maw={420}>
        <Title order={1}>CLOUDER</Title>
        {banner && (
          <Stack gap="xs" align="center">
            <Title order={3}>{banner.title}</Title>
            <Text c="dimmed" ta="center">
              {banner.body}
            </Text>
          </Stack>
        )}
        <Text c="dimmed" ta="center">
          {t('auth.signin_hint')}
        </Text>
        <Button size="lg" onClick={onSignIn}>
          {t('auth.signin')}
        </Button>
      </Stack>
    </Center>
  );
}
