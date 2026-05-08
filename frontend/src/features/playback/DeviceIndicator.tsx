import { useRef } from 'react';
import { Popover } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { IconChevronDown } from '@tabler/icons-react';
import classes from './DevicePicker.module.css';
import { iconForDeviceType, type SpotifyDevice } from './lib/deviceTypes';
import { DeviceList } from './DeviceList';
import { usePlayback } from './usePlayback';

export interface DeviceIndicatorProps {
  mode: 'full' | 'compact';
  active: SpotifyDevice | null;
  cloderTabId: string | null;
  onOpen: (anchor: HTMLElement) => void;
}

/**
 * Pill button + (on desktop) anchored Popover with the device list.
 *
 * Why the popover lives here, not in a global DevicePickerSurface: Mantine 9
 * `Popover` positions relative to its `<Popover.Target>` child. A global
 * picker with a synthetic anchor element ends up fixed-position in a corner.
 * Embedding the popover next to the button gives correct positioning.
 *
 * On mobile (`max-width: 62em`) we keep the button only — the global
 * `DevicePickerSurface` renders the `<Drawer>` from the bottom edge.
 */
export function DeviceIndicator({ mode, active, cloderTabId, onOpen }: DeviceIndicatorProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLButtonElement | null>(null);
  const isMobile = useMediaQuery('(max-width: 62em)');
  const { sdk, devices } = usePlayback();

  const Icon = active ? iconForDeviceType(active, cloderTabId) : null;
  const name = active?.name ?? t('playback.devices.no_device');
  const ariaLabel = t('playback.devices.indicator_aria', { name });

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

  const button = (
    <button
      ref={ref}
      type="button"
      className={`${classes.indicator} ${mode === 'compact' ? classes.indicatorCompact : ''}`}
      onClick={() => ref.current && onOpen(ref.current)}
      aria-label={ariaLabel}
    >
      {Icon ? <Icon size={14} aria-hidden /> : null}
      <span>{name}</span>
      {mode === 'full' ? <IconChevronDown size={12} aria-hidden /> : null}
    </button>
  );

  // Mobile: bare button. Drawer is mounted globally in DevicePickerSurface.
  if (isMobile) return button;

  // Desktop: anchor a Popover to this button.
  return (
    <Popover
      opened={devices.isOpen}
      onChange={(o) => {
        if (!o) devices.close();
      }}
      position="bottom-end"
      offset={6}
      shadow="md"
      width={280}
      withinPortal
    >
      <Popover.Target>{button}</Popover.Target>
      <Popover.Dropdown p={0}>
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
      </Popover.Dropdown>
    </Popover>
  );
}
