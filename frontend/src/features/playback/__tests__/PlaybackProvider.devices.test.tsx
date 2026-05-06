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
