import { useEffect, useRef, useState } from 'react';
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

  // OAuth `code` is single-use; Spotify rejects the second exchange with 400.
  // React 18 StrictMode runs effects twice in dev (mount → cleanup → mount),
  // and a `cancelled` flag inside the effect can't prevent the second fetch
  // from going out — it only suppresses its state update. We need the guard
  // outside the effect's closure. A ref persists across StrictMode's
  // double-mount, so the second effect bails before the second fetch fires.
  const exchanged = useRef(false);

  useEffect(() => {
    if (!code || !state) {
      setError({ title: t('auth.oauth_failed'), body: t('auth.missing_params') });
      return;
    }
    if (exchanged.current) return;
    exchanged.current = true;

    // No `cancelled` flag here. StrictMode's cleanup runs after mount-1 and
    // would set cancelled=true before fetch-1 even resolves, swallowing the
    // successful response (we'd see "Signing you in…" forever despite the
    // backend having minted a session). The `exchanged` ref already prevents
    // a duplicate fetch on mount-2. Letting fetch-1 always update state is
    // safe — navigate() during teardown is a no-op, signIn() into a
    // remounted-or-unmounted tree is harmless because tokenStore + dispatch
    // are external/stable.
    api<CallbackResponse>(
      `/auth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`,
    )
      .then((res) => {
        signIn(res.user, res.access_token, res.expires_in);
        navigate('/', { replace: true });
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.code === 'account_error') {
          setError({ title: t('auth.premium_required'), body: t('auth.premium_body') });
        } else {
          setError({ title: t('auth.oauth_failed'), body: t('auth.oauth_failed_body') });
        }
      });
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
