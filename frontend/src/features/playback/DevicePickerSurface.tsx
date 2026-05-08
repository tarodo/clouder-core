import { useEffect } from 'react';
import { useMediaQuery } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { DeviceList } from './DeviceList';
import { DeviceDrawer } from './DeviceDrawer';
import { usePlayback } from './usePlayback';

/**
 * Mobile-only picker surface: renders the bottom `<Drawer>`.
 *
 * Desktop: each `DeviceIndicator` embeds its own `<Popover>` so it anchors
 * correctly to the indicator pill (Mantine 9 `Popover` needs a real
 * `<Popover.Target>` child — a global picker would float in a corner).
 */
export function DevicePickerSurface() {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 62em)');
  const { sdk, devices } = usePlayback();

  // Eagerly refresh the device list whenever the picker opens — regardless of
  // whether the SDK has initialised yet. This makes the picker usable before
  // the user has pressed Play for the first time.
  useEffect(() => {
    if (devices.isOpen) {
      void devices.refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [devices.isOpen]);

  if (!isMobile) return null;

  const onPick = async (deviceId: string) => {
    try {
      await devices.pick(deviceId);
    } catch (err) {
      const message = err instanceof Error ? err.message : '';
      const is404 = message.includes('spotify_api_404');
      notifications.show({
        color: 'red',
        message: is404
          ? t('playback.toasts.device_offline')
          : t('playback.toasts.device_switch_failed'),
      });
    }
  };

  const sdkReadyForPicker = sdk.ready || devices.list.length > 0;

  return (
    <DeviceDrawer opened={devices.isOpen} onClose={devices.close}>
      <DeviceList
        devices={devices.list}
        active={devices.active}
        cloderTabId={devices.cloderTabId}
        isLoading={devices.isLoading}
        error={devices.error}
        sdkReady={sdkReadyForPicker}
        onPick={onPick}
        onRefresh={() => void devices.refresh()}
      />
    </DeviceDrawer>
  );
}
