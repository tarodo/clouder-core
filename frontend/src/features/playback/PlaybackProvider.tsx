import {
  createContext,
  useCallback,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useNavigate } from 'react-router';
import type {
  BindQueueArgs,
  PlaybackTrack,
  QueueSource,
  QueueStatus,
  SdkError,
} from './lib/types';
import { loadSpotifySdk } from './lib/sdkLoader';
import { clampMs, pctToMs } from './lib/seekHotkeys';
import { findNextPlayable } from './lib/skipNullSpotifyId';
import { spotifyTokenStore } from '../../auth/spotifyTokenStore';
import { spotifyApi } from './api/spotifyWebApi';
import { useAuth } from '../../auth/useAuth';

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
    __schedulePendingAdvance?: (direction: 1 | -1, delayMs: number) => void;
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
  const { refresh } = useAuth();
  const navigate = useNavigate();
  const onAuthExpired = useCallback(() => refresh(), [refresh]);

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
  const pendingAdvanceTimerRef = useRef<number | null>(null);
  const [sdkReady, setSdkReady] = useState(false);
  const [sdkError, setSdkError] = useState<SdkError | null>(null);

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
      player.addListener('initialization_error', ({ message }: { message: string }) => {
        setSdkError({ kind: 'init', message });
      });
      player.addListener('authentication_error', ({ message }: { message: string }) => {
        setSdkError({ kind: 'auth', message });
        void refresh();
      });
      player.addListener('account_error', ({ message }: { message: string }) => {
        setSdkError({ kind: 'account', message });
        navigate('/auth/premium-required');
      });
      player.addListener('playback_error', ({ message }: { message: string }) => {
        setSdkError({ kind: 'playback', message });
        queueDispatch({ type: 'STATUS', status: 'error' });
      });
      await player.connect();
    })();
    return sdkInitRef.current;
  }, [refresh, navigate]);

  const play = useCallback(
    async (idx?: number) => {
      await ensureSdk();
      const player = playerRef.current;
      const deviceId = deviceIdRef.current;
      if (!player || !deviceId) return;

      const targetIdx = idx ?? queue.cursor;
      const track = queue.tracks[targetIdx];
      if (!track || !track.spotify_id) return;

      await player.activateElement();
      if (idx !== undefined && idx !== queue.cursor) {
        queueDispatch({ type: 'CURSOR', cursor: idx });
        onCursorChangeRef.current?.(idx);
      }
      // PlaybackProvider doesn't read `track_window.current_track` from
      // `player_state_changed`, so source-of-truth `track.current` comes from
      // the queue cursor at play time. PlaybackChrome's MiniBar visibility
      // gate (`track.current !== null`) and CurateSession's PlayerCard title
      // both depend on this. Keep `positionMs/durationMs` whatever the SDK
      // last reported.
      setTrack((prev) => ({ ...prev, current: track }));
      queueDispatch({ type: 'STATUS', status: 'loading' });
      await spotifyApi.play(
        { uris: [`spotify:track:${track.spotify_id}`], deviceId },
        { onAuthExpired },
      );
    },
    [queue.cursor, queue.tracks, ensureSdk, onAuthExpired],
  );

  const pause = useCallback(async () => {
    await playerRef.current?.pause();
  }, []);

  const togglePlayPause = useCallback(async () => {
    await ensureSdk();
    await playerRef.current?.togglePlay();
  }, [ensureSdk]);

  const bindQueue = useCallback((args: BindQueueArgs) => {
    onCursorChangeRef.current = args.onCursorChange;
    queueDispatch({ type: 'BIND', source: args.source, tracks: args.tracks, cursor: args.cursor });
  }, []);

  const advance = useCallback(
    async (direction: 1 | -1) => {
      const startIndex = queue.cursor + direction;
      const next = findNextPlayable(queue.tracks, startIndex, direction);
      if (next == null) {
        queueDispatch({ type: 'STATUS', status: 'ended' });
        await playerRef.current?.pause();
        return;
      }
      queueDispatch({ type: 'CURSOR', cursor: next });
      onCursorChangeRef.current?.(next);
      const t = queue.tracks[next];
      const deviceId = deviceIdRef.current;
      if (!t || !t.spotify_id || !deviceId) return;
      // Mirror play() — populate track.current from queue at the moment we
      // initiate playback so MiniBar / PlayerCard see the right track.
      setTrack((prev) => ({ ...prev, current: t }));
      await spotifyApi.play(
        { uris: [`spotify:track:${t.spotify_id}`], deviceId },
        { onAuthExpired },
      );
    },
    [queue.cursor, queue.tracks, onAuthExpired],
  );

  const next = useCallback(() => advance(+1), [advance]);
  const prev = useCallback(() => advance(-1), [advance]);

  const seekMs = useCallback(
    async (ms: number) => {
      const clamped = clampMs(ms, track.durationMs || 0);
      await playerRef.current?.seek(clamped);
    },
    [track.durationMs],
  );

  const seekPct = useCallback(
    async (p: number) => {
      await seekMs(pctToMs(p, track.durationMs || 0));
    },
    [seekMs, track.durationMs],
  );

  const cancelPendingAdvance = useCallback(() => {
    if (pendingAdvanceTimerRef.current != null) {
      window.clearTimeout(pendingAdvanceTimerRef.current);
      pendingAdvanceTimerRef.current = null;
    }
  }, []);

  const __schedulePendingAdvance = useCallback(
    (direction: 1 | -1, delayMs: number) => {
      if (pendingAdvanceTimerRef.current != null) {
        window.clearTimeout(pendingAdvanceTimerRef.current);
      }
      pendingAdvanceTimerRef.current = window.setTimeout(() => {
        pendingAdvanceTimerRef.current = null;
        void advance(direction);
      }, delayMs);
    },
    [advance],
  );

  const clearQueue = useCallback(() => {
    cancelPendingAdvance();
    void playerRef.current?.pause();
    queueDispatch({ type: 'CLEAR' });
    setTrack({ current: null, positionMs: 0, durationMs: 0 });
    onCursorChangeRef.current = null;
  }, [cancelPendingAdvance]);

  const value = useMemo<PlaybackContextValue>(
    () => ({
      queue,
      track,
      sdk: { ready: sdkReady, error: sdkError },
      controls: {
        play,
        pause,
        togglePlayPause,
        next,
        prev,
        seekMs,
        seekPct,
        bindQueue,
        clearQueue,
        cancelPendingAdvance,
        __schedulePendingAdvance,
        openSpotifyExternal: (uri) => {
          window.open(
            uri.replace('spotify:track:', 'https://open.spotify.com/track/'),
            '_blank',
            'noopener',
          );
        },
      },
    }),
    [
      queue,
      track,
      sdkReady,
      sdkError,
      play,
      pause,
      togglePlayPause,
      next,
      prev,
      seekMs,
      seekPct,
      bindQueue,
      clearQueue,
      cancelPendingAdvance,
      __schedulePendingAdvance,
    ],
  );

  return <PlaybackContext.Provider value={value}>{children}</PlaybackContext.Provider>;
}
