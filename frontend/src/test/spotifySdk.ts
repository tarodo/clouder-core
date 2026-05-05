import { vi } from 'vitest';

type Listener = (state: unknown) => void;

export interface FakeSpotifyPlayer {
  connect: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
  togglePlay: ReturnType<typeof vi.fn>;
  pause: ReturnType<typeof vi.fn>;
  resume: ReturnType<typeof vi.fn>;
  seek: ReturnType<typeof vi.fn>;
  activateElement: ReturnType<typeof vi.fn>;
  addListener: (event: string, cb: Listener) => boolean;
  removeListener: (event: string) => boolean;
  __emit: (event: string, payload: unknown) => void;
  __listeners: Map<string, Listener[]>;
}

export function createFakeSpotifyPlayer(overrides?: Partial<FakeSpotifyPlayer>): FakeSpotifyPlayer {
  const listeners = new Map<string, Listener[]>();
  const player: FakeSpotifyPlayer = {
    connect: vi.fn().mockResolvedValue(true),
    disconnect: vi.fn(),
    togglePlay: vi.fn().mockResolvedValue(undefined),
    pause: vi.fn().mockResolvedValue(undefined),
    resume: vi.fn().mockResolvedValue(undefined),
    seek: vi.fn().mockResolvedValue(undefined),
    activateElement: vi.fn().mockResolvedValue(undefined),
    addListener: (event, cb) => {
      const arr = listeners.get(event) ?? [];
      arr.push(cb);
      listeners.set(event, arr);
      return true;
    },
    removeListener: (event) => {
      listeners.delete(event);
      return true;
    },
    __emit: (event, payload) => {
      (listeners.get(event) ?? []).forEach((cb) => cb(payload));
    },
    __listeners: listeners,
    ...overrides,
  };
  return player;
}

/**
 * Install a fake Spotify global before tests that mount PlaybackProvider.
 * Call inside beforeEach. Returns a handle to retrieve the most recently
 * created player (the SDK constructor is called inside PlaybackProvider).
 */
export function installSpotifySdkMock(): { getLatest: () => FakeSpotifyPlayer | null } {
  let latest: FakeSpotifyPlayer | null = null;
  (window as unknown as { Spotify: unknown }).Spotify = {
    Player: vi.fn().mockImplementation((_opts: unknown) => {
      latest = createFakeSpotifyPlayer();
      return latest;
    }),
  };
  // Trigger SDK-ready callback synchronously in tests.
  queueMicrotask(() => {
    window.onSpotifyWebPlaybackSDKReady?.();
  });
  return { getLatest: () => latest };
}

export function uninstallSpotifySdkMock(): void {
  delete (window as unknown as { Spotify?: unknown }).Spotify;
  delete (window as unknown as { onSpotifyWebPlaybackSDKReady?: unknown }).onSpotifyWebPlaybackSDKReady;
}
