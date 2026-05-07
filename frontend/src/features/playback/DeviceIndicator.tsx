import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { IconChevronDown } from '@tabler/icons-react';
import classes from './DevicePicker.module.css';
import { iconForDeviceType, type SpotifyDevice } from './lib/deviceTypes';

export interface DeviceIndicatorProps {
  mode: 'full' | 'compact';
  active: SpotifyDevice | null;
  cloderTabId: string | null;
  onOpen: (anchor: HTMLElement) => void;
}

export function DeviceIndicator({ mode, active, cloderTabId, onOpen }: DeviceIndicatorProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLButtonElement | null>(null);
  const Icon = active ? iconForDeviceType(active, cloderTabId) : null;
  const name = active?.name ?? t('playback.devices.no_device');
  const ariaLabel = t('playback.devices.indicator_aria', { name });
  return (
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
}
