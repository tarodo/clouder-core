import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { MemoryRouter } from 'react-router';
import { testTheme } from '../../../test/theme';
import { DevicePickerSurface } from '../DevicePickerSurface';
import { PlaybackProvider } from '../PlaybackProvider';
import { AuthProvider } from '../../../auth/AuthProvider';
import { spotifyApi } from '../api/spotifyWebApi';
import { spotifyTokenStore } from '../../../auth/spotifyTokenStore';
import { usePlayback } from '../usePlayback';

function Trigger() {
  const { devices } = usePlayback();
  return <button onClick={() => devices.open(null)}>open</button>;
}

const wrapDesktop = (children: React.ReactNode) => (
  <MantineProvider theme={testTheme}>
    <Notifications />
    <MemoryRouter>
      <AuthProvider>
        <PlaybackProvider>
          {children}
          <DevicePickerSurface />
        </PlaybackProvider>
      </AuthProvider>
    </MemoryRouter>
  </MantineProvider>
);

/** Install a fake Spotify SDK that fires `ready` synchronously on connect(). */
function installFakeSdk(deviceId: string) {
  let readyCb: ((p: { device_id: string }) => void) | null = null;
  const player = {
    addListener: vi.fn((event: string, cb: (p: { device_id: string }) => void) => {
      if (event === 'ready') readyCb = cb;
    }),
    connect: vi.fn(async () => {
      readyCb?.({ device_id: deviceId });
      return true;
    }),
    activateElement: vi.fn(async () => {}),
    pause: vi.fn(async () => {}),
    togglePlay: vi.fn(async () => {}),
    seek: vi.fn(async () => {}),
    disconnect: vi.fn(),
  };
  (window as unknown as { Spotify: unknown }).Spotify = { Player: vi.fn(() => player) };
  return player;
}

const MOCK_DEVICES = [
  { id: 'd1', name: 'Laptop', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
];

beforeEach(() => {
  spotifyTokenStore.set('tok');
  installFakeSdk('d1');
  vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue(MOCK_DEVICES);
  vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue(undefined);
  // Force desktop breakpoint by default
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn((q: string) => ({
      matches: q.includes('min-width'),
      media: q,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});
afterEach(() => {
  spotifyTokenStore.set(null);
  delete (window as unknown as { Spotify?: unknown }).Spotify;
  vi.restoreAllMocks();
});

describe('DevicePickerSurface', () => {
  it('renders nothing on desktop — DeviceIndicator hosts its own Popover', async () => {
    // Desktop popover anchoring lives in DeviceIndicator (so Mantine 9
    // Popover.Target wraps the actual button). DevicePickerSurface only
    // renders the mobile Drawer.
    const user = userEvent.setup();
    render(wrapDesktop(<Trigger />));
    await user.click(screen.getByText('open'));
    // No dialog or device-row button should appear from this surface.
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Laptop' })).toBeNull();
  });

  it('renders Drawer when mobile (max-width:62em matches)', async () => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn((q: string) => ({
        matches: q.includes('max-width'),
        media: q,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
    const user = userEvent.setup();
    render(wrapDesktop(<Trigger />));
    await user.click(screen.getByText('open'));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Laptop' })).toBeInTheDocument();
  });
});
