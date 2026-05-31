import { useEffect, useRef, useState } from 'react';
import { Anchor, Button, Code, Group, Loader, Modal, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { useRequestDeviceCode, usePollYtmusic } from '../hooks/useYtmusicConnect';

export interface YtMusicConnectModalProps {
  opened: boolean;
  onClose: () => void;
  onConnected: () => void;
}

export function YtMusicConnectModal({ opened, onClose, onConnected }: YtMusicConnectModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const requestCode = useRequestDeviceCode();
  const poll = usePollYtmusic();
  const [code, setCode] = useState<{ userCode: string; url: string; deviceCode: string; interval: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Request a device code when the modal opens.
  useEffect(() => {
    if (!opened) return;
    setError(null);
    setCode(null);
    requestCode
      .mutateAsync()
      .then((r) =>
        setCode({ userCode: r.user_code, url: r.verification_url, deviceCode: r.device_code, interval: r.interval }),
      )
      .catch(() => setError(t('playlists.ytmusic_connect.error')));
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  // Poll until connected.
  useEffect(() => {
    if (!opened || !code) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await poll.mutateAsync({ deviceCode: code.deviceCode });
        if (cancelled) return;
        if (r.connected) {
          qc.invalidateQueries({ queryKey: ['me'] });
          onConnected();
          return;
        }
        timer.current = setTimeout(tick, Math.max(code.interval, 1) * 1000);
      } catch {
        if (!cancelled) setError(t('playlists.ytmusic_connect.expired'));
      }
    };
    timer.current = setTimeout(tick, Math.max(code.interval, 1) * 1000);
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, code]);

  return (
    <Modal opened={opened} onClose={onClose} title={t('playlists.ytmusic_connect.title')} centered>
      <Stack gap="md">
        {error ? (
          <Text c="red">{error}</Text>
        ) : code ? (
          <>
            <Text>{t('playlists.ytmusic_connect.body')}</Text>
            <Code fz="xl" ta="center">{code.userCode}</Code>
            <Anchor href={code.url} target="_blank" rel="noopener noreferrer">
              {t('playlists.ytmusic_connect.open_link')}
            </Anchor>
            <Group gap="xs">
              <Loader size="xs" />
              <Text size="sm" c="dimmed">{t('playlists.ytmusic_connect.waiting')}</Text>
            </Group>
          </>
        ) : (
          <Group justify="center"><Loader /></Group>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{t('playlists.form.cancel')}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
