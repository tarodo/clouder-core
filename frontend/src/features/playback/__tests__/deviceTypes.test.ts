import { describe, expect, it } from 'vitest';
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
} from '@tabler/icons-react';
import { iconForDeviceType, type SpotifyDevice } from '../lib/deviceTypes';

const baseDevice = (over: Partial<SpotifyDevice>): SpotifyDevice => ({
  id: 'd1',
  name: 'Device',
  type: 'Computer',
  is_active: false,
  is_private_session: false,
  is_restricted: false,
  volume_percent: null,
  ...over,
});

describe('iconForDeviceType', () => {
  it.each([
    ['Smartphone', IconDeviceMobile],
    ['Tablet', IconDeviceTablet],
    ['Speaker', IconDeviceSpeaker],
    ['TV', IconDeviceTv],
    ['CastVideo', IconCast],
    ['CastAudio', IconBroadcast],
    ['AVR', IconDeviceTv],
    ['STB', IconDeviceTv],
    ['AudioDongle', IconHeadphones],
    ['GameConsole', IconDeviceGamepad],
    ['AutomobileVoice', IconCar],
    ['Unknown', IconDeviceUnknown],
  ] as const)('maps %s to expected icon', (type, icon) => {
    expect(iconForDeviceType(baseDevice({ type }), null)).toBe(icon);
  });

  it('maps Computer to IconDeviceLaptop by default', () => {
    expect(iconForDeviceType(baseDevice({ id: 'x', type: 'Computer' }), 'cloder-id')).toBe(
      IconDeviceLaptop,
    );
  });

  it('overrides Computer with IconCloud when device.id === cloderTabId', () => {
    expect(iconForDeviceType(baseDevice({ id: 'cloder-id', type: 'Computer' }), 'cloder-id')).toBe(
      IconCloud,
    );
  });

  it('does NOT override non-Computer types even when id matches cloderTabId', () => {
    expect(
      iconForDeviceType(baseDevice({ id: 'cloder-id', type: 'Smartphone' }), 'cloder-id'),
    ).toBe(IconDeviceMobile);
  });
});
