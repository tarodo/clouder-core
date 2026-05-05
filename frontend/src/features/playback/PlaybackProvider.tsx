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

type QueueState = {
  source: QueueSource | null;
  tracks: readonly PlaybackTrack[];
  cursor: number;
  status: QueueStatus;
};

type QueueAction =
  | { type: 'BIND'; source: QueueSource; tracks: readonly PlaybackTrack[]; cursor: number }
  | { type: 'CURSOR'; cursor: number }
  | { type: 'STATUS'; status: QueueStatus }
  | { type: 'CLEAR' };

function queueReducer(state: QueueState, action: QueueAction): QueueState {
  switch (action.type) {
    case 'BIND':
      return { source: action.source, tracks: action.tracks, cursor: action.cursor, status: state.status };
    case 'CURSOR':
      return { ...state, cursor: action.cursor };
    case 'STATUS':
      return { ...state, status: action.status };
    case 'CLEAR':
      return { source: null, tracks: [], cursor: 0, status: 'idle' };
    default:
      return state;
  }
}

export function PlaybackProvider({ children }: { children: ReactNode }) {
  const [queue, queueDispatch] = useReducer(queueReducer, {
    source: null,
    tracks: [] as readonly PlaybackTrack[],
    cursor: 0,
    status: 'idle' as QueueStatus,
  });

  const [track, setTrack] = useState<{
    current: PlaybackTrack | null;
    positionMs: number;
    durationMs: number;
  }>({ current: null, positionMs: 0, durationMs: 0 });

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
      player.addListener('player_state_changed', (sdkState: Spotify.PlaybackState | null) => {
        if (!sdkState) return;
        setTrack((prev) => ({
          current: prev.current,
          positionMs: sdkState.position,
          durationMs: sdkState.duration,
        }));
        queueDispatch({ type: 'STATUS', status: sdkState.paused ? 'paused' : 'playing' });
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

  const bindQueue = useCallback((args: BindQueueArgs) => {
    onCursorChangeRef.current = args.onCursorChange;
    queueDispatch({ type: 'BIND', source: args.source, tracks: args.tracks, cursor: args.cursor });
  }, []);

  const value = useMemo<PlaybackContextValue>(
    () => ({
      queue,
      track,
      sdk: { ready: sdkReady, error: null /* set in T18 */ },
      controls: {
        play,
        pause: async () => {},
        togglePlayPause: async () => {},
        next: async () => {},
        prev: async () => {},
        seekMs: async () => {},
        seekPct: async () => {},
        bindQueue,
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
    [queue, track, sdkReady, play, bindQueue],
  );

  return <PlaybackContext.Provider value={value}>{children}</PlaybackContext.Provider>;
}
