// frontend/src/features/playback/__tests__/integration.f7.test.tsx
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { MemoryRouter } from 'react-router';
import { testTheme } from '../../../test/theme';
import { PlaybackProvider } from '../PlaybackProvider';
import { DevicePickerSurface } from '../DevicePickerSurface';
import { DeviceIndicator } from '../DeviceIndicator';
import { usePlayback } from '../usePlayback';
import { spotifyApi } from '../api/spotifyWebApi';
import { spotifyTokenStore } from '../../../auth/spotifyTokenStore';
import { AuthProvider } from '../../../auth/AuthProvider';

function App() {
  const { sdk, devices, controls } = usePlayback();
  return (
    <>
      <button onClick={() => controls.togglePlayPause()}>boot</button>
      <DeviceIndicator
        mode="full"
        active={devices.active}
        cloderTabId={devices.cloderTabId}
        onOpen={(a) => devices.open(a)}
      />
      <DevicePickerSurface />
      <span data-testid="active">{devices.active?.name ?? 'none'}</span>
      <span data-testid="ready">{String(sdk.ready)}</span>
    </>
  );
}

const wrap = (ui: React.ReactNode) => (
  <MantineProvider theme={testTheme}>
    <Notifications />
    <MemoryRouter>
      <AuthProvider>
        <PlaybackProvider>{ui}</PlaybackProvider>
      </AuthProvider>
    </MemoryRouter>
  </MantineProvider>
);

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
  };
  (window as unknown as { Spotify: unknown }).Spotify = { Player: vi.fn(() => player) };
  return player;
}

beforeEach(() => {
  spotifyTokenStore.set('tok');
});
afterEach(() => {
  spotifyTokenStore.set(null);
  window.localStorage.clear();
  vi.restoreAllMocks();
  delete (window as unknown as { Spotify?: unknown }).Spotify;
});

describe('F7 integration · cold start', () => {
  it('no last_device — falls back to CLOUDER tab; indicator shows CLOUDER', async () => {
    installFakeSdk('cloder-id');
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER Web Player', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    const transfer = vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    const user = userEvent.setup();
    render(wrap(<App />));
    await user.click(screen.getByText('boot'));
    await waitFor(() => expect(transfer).toHaveBeenCalled());
    expect(transfer).toHaveBeenCalledWith({ deviceId: 'cloder-id', play: false }, expect.any(Object));
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('CLOUDER Web Player'));
    expect(window.localStorage.getItem('clouder.last_device_id')).toBeNull();
  });
});

describe('F7 integration · restore + open', () => {
  it('last_device online — silent restore to that device', async () => {
    installFakeSdk('cloder-id');
    window.localStorage.setItem('clouder.last_device_id', 'iphone');
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'iphone', name: 'iPhone', type: 'Smartphone', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    const transfer = vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    const user = userEvent.setup();
    render(wrap(<App />));
    await user.click(screen.getByText('boot'));
    await waitFor(() => expect(transfer).toHaveBeenCalledWith({ deviceId: 'iphone', play: false }, expect.any(Object)));
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('iPhone'));
    expect(window.localStorage.getItem('clouder.last_device_id')).toBe('iphone'); // unchanged
  });

  it('last_device offline — fallback CLOUDER; localStorage retained', async () => {
    installFakeSdk('cloder-id');
    window.localStorage.setItem('clouder.last_device_id', 'iphone');
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    const transfer = vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    const user = userEvent.setup();
    render(wrap(<App />));
    await user.click(screen.getByText('boot'));
    await waitFor(() => expect(transfer).toHaveBeenCalledWith({ deviceId: 'cloder-id', play: false }, expect.any(Object)));
    expect(window.localStorage.getItem('clouder.last_device_id')).toBe('iphone'); // unchanged
  });

  it('open picker desktop renders Popover with list', async () => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn((q: string) => ({
        matches: q.includes('min-width'), media: q, onchange: null,
        addListener: vi.fn(), removeListener: vi.fn(),
        addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
      })),
    });
    installFakeSdk('cloder-id');
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    const user = userEvent.setup();
    render(wrap(<App />));
    await user.click(screen.getByText('boot'));
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('CLOUDER'));
    await user.click(screen.getByRole('button', { name: /Switch playback device/i }));
    expect(await screen.findByRole('button', { name: 'CLOUDER' })).toBeInTheDocument();
  });

  it('open picker mobile renders Drawer dialog with list', async () => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn((q: string) => ({
        matches: q.includes('max-width'), media: q, onchange: null,
        addListener: vi.fn(), removeListener: vi.fn(),
        addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
      })),
    });
    installFakeSdk('cloder-id');
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    const user = userEvent.setup();
    render(wrap(<App />));
    await user.click(screen.getByText('boot'));
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('CLOUDER'));
    await user.click(screen.getByRole('button', { name: /Switch playback device/i }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });
});
