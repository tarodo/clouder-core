import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { act, render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../test/theme';
import { PlaybackProvider } from '../PlaybackProvider';
import { usePlayback } from '../usePlayback';
import { spotifyApi } from '../api/spotifyWebApi';
import { spotifyTokenStore } from '../../../auth/spotifyTokenStore';
import { AuthProvider } from '../../../auth/AuthProvider';

function Probe({ onValue }: { onValue: (v: ReturnType<typeof usePlayback>) => void }) {
  const v = usePlayback();
  onValue(v);
  return null;
}

const wrap = (children: React.ReactNode) => (
  <MantineProvider theme={testTheme}>
    <MemoryRouter>
      <AuthProvider>
        <PlaybackProvider>{children}</PlaybackProvider>
      </AuthProvider>
    </MemoryRouter>
  </MantineProvider>
);

describe('PlaybackProvider.devices.refresh', () => {
  beforeEach(() => {
    spotifyTokenStore.set('tok');
  });
  afterEach(() => {
    spotifyTokenStore.set(null);
    vi.restoreAllMocks();
  });

  it('populates list from getMyDevices', async () => {
    const devices = [
      { id: 'd1', name: 'Laptop', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: 60 },
    ];
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue(devices);
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.devices.refresh();
    });
    await waitFor(() => expect(captured!.devices.list).toEqual(devices));
    expect(captured!.devices.error).toBeNull();
  });

  it('sets error=network on rejection', async () => {
    vi.spyOn(spotifyApi, 'getMyDevices').mockRejectedValue(new Error('spotify_api_500'));
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.devices.refresh();
    });
    await waitFor(() => expect(captured!.devices.error).toBe('network'));
  });
});

describe('PlaybackProvider.devices.pick', () => {
  beforeEach(() => {
    spotifyTokenStore.set('tok');
  });
  afterEach(() => {
    spotifyTokenStore.set(null);
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it('happy path — calls transferMyPlayback, persists last_device_id, closes picker', async () => {
    const devices = [
      { id: 'cloder', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'speaker', name: 'KitchenSpeaker', type: 'Speaker' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue(devices);
    const transfer = vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.devices.refresh();
    });
    act(() => { captured!.devices.open(null); });
    expect(captured!.devices.isOpen).toBe(true);

    await act(async () => {
      await captured!.devices.pick('speaker');
    });

    expect(transfer).toHaveBeenCalledWith({ deviceId: 'speaker', play: false }, expect.any(Object));
    expect(window.localStorage.getItem('clouder.last_device_id')).toBe('speaker');
    expect(captured!.devices.isOpen).toBe(false);
    expect(captured!.devices.active?.id).toBe('speaker');
  });

  it('on 404 — refreshes list and keeps picker open', async () => {
    const initial = [
      { id: 'cloder', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'stale', name: 'OldPhone', type: 'Smartphone' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    const after = [initial[0]!];
    vi.spyOn(spotifyApi, 'getMyDevices')
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(after);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockRejectedValue(new Error('spotify_api_404'));

    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.devices.refresh();
    });
    act(() => { captured!.devices.open(null); });

    await act(async () => {
      await captured!.devices.pick('stale').catch(() => {}); // pick rethrows; swallow
    });

    await waitFor(() => expect(captured!.devices.list).toEqual(after));
    expect(captured!.devices.isOpen).toBe(true);
    expect(window.localStorage.getItem('clouder.last_device_id')).toBeNull();
  });

  it('on 5xx — keeps picker open, no auto-refresh, no last_device write', async () => {
    const devices = [
      { id: 'cloder', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'speaker', name: 'KitchenSpeaker', type: 'Speaker' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    const refresh = vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue(devices);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockRejectedValue(new Error('spotify_api_503'));

    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.devices.refresh();
    });
    refresh.mockClear();
    act(() => { captured!.devices.open(null); });

    await act(async () => {
      await captured!.devices.pick('speaker').catch(() => {});
    });

    expect(refresh).not.toHaveBeenCalled();
    expect(captured!.devices.isOpen).toBe(true);
    expect(window.localStorage.getItem('clouder.last_device_id')).toBeNull();
  });
});
