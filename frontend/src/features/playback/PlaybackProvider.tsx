import {
  createContext,
  useCallback,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type {
  BindQueueArgs,
  PlaybackTrack,
  QueueSource,
  QueueStatus,
  SdkError,
} from './lib/types';
import { loadSpotifySdk } from './lib/sdkLoader';
import { spotifyTokenStore } from '../../auth/spotifyTokenStore';
import { spotifyApi } from './api/spotifyWebApi';

export interface PlaybackContextValue {
  queue: {
    source: QueueSource | null;
    tracks: readonly PlaybackTrack[];
    cursor: number;
    status: QueueStatus;
  };
  track: {
    current: PlaybackTrack | null;
    positionMs: number;
    durationMs: number;
  };
  sdk: { ready: boolean; error: SdkError | null };
  controls: {
    play: (idx?: number) => Promise<void>;
    pause: () => Promise<void>;
    togglePlayPause: () => Promise<void>;
    next: () => Promise<void>;
    prev: () => Promise<void>;
    seekMs: (ms: number) => Promise<void>;
    seekPct: (p: number) => Promise<void>;
    bindQueue: (b: BindQueueArgs) => void;
    clearQueue: () => void;
    cancelPendingAdvance: () => void;
    openSpotifyExternal: (uri: string) => void;
  };
}

export const PlaybackContext = createContext<PlaybackContextValue | null>(null);

interface State {
  queue: PlaybackContextValue['queue'];
  track: PlaybackContextValue['track'];
  sdk: PlaybackContextValue['sdk'];
}

const INITIAL_STATE: State = {
  queue: { source: null, tracks: [], cursor: 0, status: 'idle' },
  track: { current: null, positionMs: 0, durationMs: 0 },
  sdk: { ready: false, error: null },
};

type Action = { type: 'noop' };

function reducer(state: State, _action: Action): State {
  return state;
}

export function PlaybackProvider({ children }: { children: ReactNode }) {
  const [state] = useReducer(reducer, INITIAL_STATE);
  const onCursorChangeRef = useRef<((next: number) => void) | null>(null);

  const sdkInitRef = useRef<Promise<void> | null>(null);
  const playerRef = useRef<Spotify.Player | null>(null);
  const deviceIdRef = useRef<string | null>(null);
  const [sdkReady, setSdkReady] = useState(false);

  const ensureSdk = useCallback(async (): Promise<void> => {
    if (sdkInitRef.current) return sdkInitRef.current;
    sdkInitRef.current = (async () => {
      await loadSpotifySdk();
      const SpotifyGlobal = (
        window as unknown as {
          Spotify: { Player: new (opts: unknown) => Spotify.Player };
        }
      ).Spotify;
      const player = new SpotifyGlobal.Player({
        name: 'CLOUDER Web Player',
        getOAuthToken: (cb: (t: string) => void) => {
          const t = spotifyTokenStore.get();
          if (t) cb(t);
        },
        volume: 0.6,
      });
      playerRef.current = player;
      player.addListener('ready', ({ device_id }: { device_id: string }) => {
        deviceIdRef.current = device_id;
        setSdkReady(true);
        void spotifyApi.transferMyPlayback({ deviceId: device_id, play: false });
      });
      player.addListener('not_ready', () => {
        setSdkReady(false);
      });
      await player.connect();
    })();
    return sdkInitRef.current;
  }, []);

  const play = useCallback(
    async (_idx?: number) => {
      await ensureSdk();
      // Real play() lands in T14 — for T12 just guarantee SDK init runs.
    },
    [ensureSdk],
  );

  const value = useMemo<PlaybackContextValue>(
    () => ({
      queue: state.queue,
      track: state.track,
      sdk: { ready: sdkReady, error: state.sdk.error },
      controls: {
        play,
        pause: async () => {},
        togglePlayPause: async () => {},
        next: async () => {},
        prev: async () => {},
        seekMs: async () => {},
        seekPct: async () => {},
        bindQueue: (args) => {
          onCursorChangeRef.current = args.onCursorChange;
        },
        clearQueue: () => {},
        cancelPendingAdvance: () => {},
        openSpotifyExternal: (uri) => {
          window.open(
            uri.replace('spotify:track:', 'https://open.spotify.com/track/'),
            '_blank',
            'noopener',
          );
        },
      },
    }),
    [state, sdkReady, play],
  );

  return <PlaybackContext.Provider value={value}>{children}</PlaybackContext.Provider>;
}
