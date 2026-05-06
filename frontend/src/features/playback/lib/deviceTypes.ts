import {
  IconBroadcast,
  IconCar,
  IconCast,
  IconCloud,
  IconDeviceGamepad,
  IconDeviceLaptop,
  IconDeviceMobile,
  IconDeviceSpeaker,
  IconDeviceTablet,
  IconDeviceTv,
  IconDeviceUnknown,
  IconHeadphones,
  type Icon,
} from '@tabler/icons-react';

export type SpotifyDeviceType =
  | 'Computer'
  | 'Smartphone'
  | 'Tablet'
  | 'Speaker'
  | 'TV'
  | 'CastVideo'
  | 'CastAudio'
  | 'AVR'
  | 'STB'
  | 'AudioDongle'
  | 'GameConsole'
  | 'AutomobileVoice'
  | 'Unknown';

export interface SpotifyDevice {
  id: string;
  name: string;
  type: SpotifyDeviceType;
  is_active: boolean;
  is_private_session: boolean;
  is_restricted: boolean;
  volume_percent: number | null;
}

export function iconForDeviceType(device: SpotifyDevice, cloderTabId: string | null): Icon {
  if (device.type === 'Computer' && cloderTabId !== null && device.id === cloderTabId) {
    return IconCloud;
  }
  switch (device.type) {
    case 'Computer':
      return IconDeviceLaptop;
    case 'Smartphone':
      return IconDeviceMobile;
    case 'Tablet':
      return IconDeviceTablet;
    case 'Speaker':
      return IconDeviceSpeaker;
    case 'TV':
    case 'AVR':
    case 'STB':
      return IconDeviceTv;
    case 'CastVideo':
      return IconCast;
    case 'CastAudio':
      return IconBroadcast;
    case 'AudioDongle':
      return IconHeadphones;
    case 'GameConsole':
      return IconDeviceGamepad;
    case 'AutomobileVoice':
      return IconCar;
    case 'Unknown':
    default:
      return IconDeviceUnknown;
  }
}
