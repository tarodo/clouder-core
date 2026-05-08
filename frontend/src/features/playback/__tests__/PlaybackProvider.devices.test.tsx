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
    window.localStorage.clear();
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

  it('flips queue.status to disconnected when active device leaves the list', async () => {
    const initial = [
      { id: 'cloder', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'speaker', name: 'KitchenSpeaker', type: 'Speaker' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    const after = [initial[0]!]; // speaker dropped
    vi.spyOn(spotifyApi, 'getMyDevices')
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(after);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    // First refresh + pick speaker as active
    await act(async () => { await captured!.devices.refresh(); });
    await act(async () => { await captured!.devices.pick('speaker'); });
    expect(captured!.devices.active?.id).toBe('speaker');
    // Second refresh returns list without speaker → status flips
    await act(async () => { await captured!.devices.refresh(); });
    await waitFor(() => expect(captured!.queue.status).toBe('disconnected'));
    expect(captured!.devices.active).toBeNull();
  });
});

// helper: install a fake SDK that fires `ready` synchronously on connect()
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

describe('PlaybackProvider bootstrap silent restore', () => {
  beforeEach(() => {
    spotifyTokenStore.set('tok');
  });
  afterEach(() => {
    spotifyTokenStore.set(null);
    window.localStorage.clear();
    vi.restoreAllMocks();
    delete (window as unknown as { Spotify?: unknown }).Spotify;
  });

  it('no last_device — falls back to CLOUDER tab', async () => {
    installFakeSdk('cloder-id');
    const list = [
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue(list);
    const transfer = vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    // Trigger ensureSdk by calling controls.togglePlayPause (calls ensureSdk).
    await act(async () => {
      await captured!.controls.togglePlayPause();
    });
    await waitFor(() => expect(transfer).toHaveBeenCalled());
    expect(transfer).toHaveBeenCalledWith({ deviceId: 'cloder-id', play: false }, expect.any(Object));
    expect(window.localStorage.getItem('clouder.last_device_id')).toBeNull();
    expect(captured!.devices.cloderTabId).toBe('cloder-id');
  });

  it('last_device saved — bootstrap stays on CLOUDER tab; localStorage retained', async () => {
    // Auto-restore was removed: device_ids change every browser session,
    // so restoring a saved id is usually stale and caused state_conflict
    // thrashing. lastDeviceStore is preserved (used only by user-explicit
    // pick — not for bootstrap).
    installFakeSdk('cloder-id');
    window.localStorage.setItem('clouder.last_device_id', 'speaker-id');
    const list = [
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'speaker-id', name: 'Kitchen', type: 'Speaker' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue(list);
    const transfer = vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.controls.togglePlayPause();
    });
    await waitFor(() => expect(transfer).toHaveBeenCalled());
    expect(transfer).toHaveBeenCalledWith({ deviceId: 'cloder-id', play: false }, expect.any(Object));
    // single transfer to CLOUDER tab — no second transfer to last_device
    expect(transfer).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem('clouder.last_device_id')).toBe('speaker-id');
  });

  it('last_device offline — falls back to CLOUDER tab', async () => {
    installFakeSdk('cloder-id');
    window.localStorage.setItem('clouder.last_device_id', 'iphone-id');
    const list = [
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      // iphone-id NOT in list
    ];
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue(list);
    const transfer = vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.controls.togglePlayPause();
    });
    await waitFor(() => expect(transfer).toHaveBeenCalled());
    expect(transfer).toHaveBeenCalledWith({ deviceId: 'cloder-id', play: false }, expect.any(Object));
    // localStorage left untouched (do NOT clear stale id — phone may come back)
    expect(window.localStorage.getItem('clouder.last_device_id')).toBe('iphone-id');
  });
});

describe('PlaybackProvider polling cadence', () => {
  beforeEach(() => {
    spotifyTokenStore.set('tok');
    vi.useFakeTimers();
  });
  afterEach(() => {
    spotifyTokenStore.set(null);
    vi.useRealTimers();
    vi.restoreAllMocks();
    delete (window as unknown as { Spotify?: unknown }).Spotify;
  });

  it('runs every 30s when picker closed, every 5s when open', async () => {
    installFakeSdk('cloder-id');
    const spy = vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.controls.togglePlayPause();   // bootstrap getMyDevices: 1 call
    });
    await vi.waitFor(() => expect(spy).toHaveBeenCalledTimes(1));

    // Picker closed: advance 30s -> +1 call
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(spy).toHaveBeenCalledTimes(2);

    // Open picker: 5s cadence
    act(() => { captured!.devices.open(null); });
    await act(async () => { vi.advanceTimersByTime(5_000); });
    expect(spy).toHaveBeenCalledTimes(3);
    await act(async () => { vi.advanceTimersByTime(5_000); });
    expect(spy).toHaveBeenCalledTimes(4);

    // Close picker: back to 30s
    act(() => { captured!.devices.close(); });
    await act(async () => { vi.advanceTimersByTime(5_000); });
    expect(spy).toHaveBeenCalledTimes(4); // no new call
    await act(async () => { vi.advanceTimersByTime(25_000); });
    expect(spy).toHaveBeenCalledTimes(5);
  });

  it('focus event fires refresh', async () => {
    installFakeSdk('cloder-id');
    const spy = vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.controls.togglePlayPause();
    });
    await vi.waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    await act(async () => { window.dispatchEvent(new Event('focus')); });
    expect(spy).toHaveBeenCalledTimes(2);
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
