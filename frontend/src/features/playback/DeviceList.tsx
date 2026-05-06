import { Anchor, Button, Skeleton, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { DeviceRow } from './DeviceRow';
import type { SpotifyDevice } from './lib/deviceTypes';

export interface DeviceListProps {
  devices: readonly SpotifyDevice[];
  active: SpotifyDevice | null;
  cloderTabId: string | null;
  isLoading: boolean;
  error: 'network' | 'auth' | null;
  sdkReady: boolean;
  onPick: (deviceId: string) => void;
  onRefresh: () => void;
}

export function DeviceList(props: DeviceListProps) {
  const { devices, active, cloderTabId, isLoading, error, sdkReady, onPick, onRefresh } = props;
  const { t } = useTranslation();

  if (!sdkReady) {
    return (
      <Stack gap="xs" p="md" data-testid="device-list-connecting">
        <Skeleton height={36} />
        <Skeleton height={36} />
        <Skeleton height={36} />
        <Text size="sm" c="dimmed" ta="center">
          {t('playback.devices.connecting')}
        </Text>
      </Stack>
    );
  }

  if (isLoading && devices.length === 0) {
    return (
      <Stack gap="xs" p="md" data-testid="device-list-loading">
        <Skeleton height={36} />
        <Skeleton height={36} />
        <Skeleton height={36} />
      </Stack>
    );
  }

  if (error === 'auth') {
    return (
      <Stack gap="xs" p="md" align="center">
        <Anchor href="/auth/login">{t('playback.devices.auth_error')}</Anchor>
      </Stack>
    );
  }

  if (error === 'network') {
    return (
      <Stack gap="xs" p="md" align="center">
        <Text size="sm" c="var(--color-danger)">
          {t('playback.devices.empty_title')}
        </Text>
        <Button size="xs" variant="light" onClick={onRefresh}>
          {t('playback.devices.retry')}
        </Button>
      </Stack>
    );
  }

  if (devices.length === 0) {
    return (
      <Stack gap="xs" p="md" align="center">
        <Text size="sm" fw={600}>
          {t('playback.devices.empty_title')}
        </Text>
        <Text size="sm" c="dimmed" ta="center">
          {t('playback.devices.empty_body')}
        </Text>
        <Button size="xs" variant="light" onClick={onRefresh}>
          {t('playback.devices.refresh')}
        </Button>
      </Stack>
    );
  }

  return (
    <Stack gap={0} py="xs">
      {devices.map((d) => (
        <DeviceRow
          key={d.id}
          device={d}
          cloderTabId={cloderTabId}
          isActive={active?.id === d.id}
          onPick={onPick}
        />
      ))}
    </Stack>
  );
}
