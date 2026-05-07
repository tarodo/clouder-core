import { Badge, Text } from '@mantine/core';
import { IconCheck } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import classes from './DevicePicker.module.css';
import { iconForDeviceType, type SpotifyDevice } from './lib/deviceTypes';

export interface DeviceRowProps {
  device: SpotifyDevice;
  cloderTabId: string | null;
  isActive: boolean;
  onPick: (deviceId: string) => void;
}

export function DeviceRow({ device, cloderTabId, isActive, onPick }: DeviceRowProps) {
  const { t } = useTranslation();
  const Icon = iconForDeviceType(device, cloderTabId);
  return (
    <button
      type="button"
      className={`${classes.row} ${isActive ? classes.rowActive : ''}`}
      onClick={() => onPick(device.id)}
      aria-label={device.name}
    >
      <Icon size={18} aria-hidden />
      <Text size="sm" flex={1} truncate>
        {device.name}
      </Text>
      {device.is_restricted ? (
        <Badge size="xs" variant="light" color="gray">
          {t('playback.devices.restricted')}
        </Badge>
      ) : null}
      {isActive ? (
        <IconCheck size={16} aria-label={t('playback.devices.active_aria')} />
      ) : null}
    </button>
  );
}
