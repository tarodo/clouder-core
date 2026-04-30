import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { Button, Center, Stack, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import { ApiError } from '../api/error';
import { FullScreenLoader } from '../components/FullScreenLoader';
import { useAuth } from '../auth/useAuth';
import type { Me } from '../auth/AuthProvider';

interface CallbackResponse {
  access_token: string;
  expires_in: number;
  user: Me;
}

export function AuthReturnPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { t } = useTranslation();
  const [error, setError] = useState<{ title: string; body: string } | null>(null);

  // Snapshot raw query values so the effect's dep list stays primitive —
  // useSearchParams returns a fresh object each render which would otherwise
  // re-fire the effect and produce duplicate /auth/callback exchanges.
  const code = params.get('code');
  const state = params.get('state');

  useEffect(() => {
    if (!code || !state) {
      setError({ title: t('auth.oauth_failed'), body: t('auth.missing_params') });
      return;
    }
    let cancelled = false;
    api<CallbackResponse>(
      `/auth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`,
    )
      .then((res) => {
        if (cancelled) return;
        signIn(res.user, res.access_token, res.expires_in);
        navigate('/', { replace: true });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.code === 'account_error') {
          setError({ title: t('auth.premium_required'), body: t('auth.premium_body') });
        } else {
          setError({ title: t('auth.oauth_failed'), body: t('auth.oauth_failed_body') });
        }
      });
    return () => {
      cancelled = true;
    };
    // signIn / navigate / t are referenced inside the effect but intentionally
    // omitted from the dep list — they're stable enough in practice, and
    // including them re-fired the effect and produced duplicate exchanges.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, state]);

  if (error) {
    return (
      <Center mih="100vh" p="xl">
        <Stack align="center" gap="md" maw={420}>
          <Title order={2} ta="center">
            {error.title}
          </Title>
          <Text c="dimmed" ta="center">
            {error.body}
          </Text>
          <Button onClick={() => navigate('/login', { replace: true })}>
            {t('auth.signin')}
          </Button>
        </Stack>
      </Center>
    );
  }

  return <FullScreenLoader copy={t('auth.signing_in')} />;
}
