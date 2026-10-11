import { describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router';
import { AuthContext, type AuthContextValue } from '../../../auth/AuthProvider';
import { PlaybackProvider } from '../PlaybackProvider';
import { usePlayback } from '../usePlayback';
import { loadSpotifySdk } from '../lib/sdkLoader';

vi.mock('../../../demo/mode', () => ({ isDemo: () => true }));
vi.mock('../lib/sdkLoader', () => ({
  loadSpotifySdk: vi.fn(() => Promise.resolve()),
  __resetSdkLoaderForTests: vi.fn(),
}));

const auth: AuthContextValue = {
  state: {
    status: 'authenticated',
    user: {
      id: 'u',
      spotify_id: 's',
      display_name: 'Demo',
      is_admin: true,
      ytmusic_connected: false,
    },
    expiresAt: Date.now() + 1_800_000,
    spotifyAccessToken: 'demo',
  },
  signIn: vi.fn(),
  signOut: vi.fn(),
  refresh: vi.fn().mockResolvedValue(true),
};

function Wrapper({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter>
      <AuthContext.Provider value={auth}>
        <PlaybackProvider>{children}</PlaybackProvider>
      </AuthContext.Provider>
    </MemoryRouter>
  );
}

describe('PlaybackProvider in the demo', () => {
  it('never loads the Spotify SDK and shows the disconnected state', async () => {
    const { result } = renderHook(() => usePlayback(), { wrapper: Wrapper });
    expect(result.current.sdk.error?.kind).toBe('init');
    await act(async () => {
      await result.current.controls.prewarm();
    });
    expect(loadSpotifySdk).not.toHaveBeenCalled();
  });
});
