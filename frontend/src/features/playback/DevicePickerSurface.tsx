import { useEffect } from 'react';
import { useMediaQuery } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { DeviceList } from './DeviceList';
import { DevicePicker } from './DevicePicker';
import { DeviceDrawer } from './DeviceDrawer';
import { usePlayback } from './usePlayback';

export function DevicePickerSurface() {
  const { t } = useTranslation();
  // Mantine 9 breakpoint md = 62em. Use max-width to detect mobile.
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

  // Show the device list without the "Connecting" skeleton if we already have
  // a populated list from the REST API — the SDK player doesn't need to be
  // running for the user to browse and pick a device.
  const sdkReadyForPicker = sdk.ready || devices.list.length > 0;

  const list = (
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
  );

  if (isMobile) {
    return (
      <DeviceDrawer opened={devices.isOpen} onClose={devices.close}>
        {list}
      </DeviceDrawer>
    );
  }
  return (
    <DevicePicker opened={devices.isOpen} onClose={devices.close}>
      {list}
    </DevicePicker>
  );
}
