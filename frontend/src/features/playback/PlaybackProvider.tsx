import {
  createContext,
  useCallback,
  useEffect,
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
    play: (idx?: number, overrideTrack?: PlaybackTrack) => Promise<void>;
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
  const deviceReadyRef = useRef<{ promise: Promise<void>; resolve: () => void } | null>(null);
  const pendingAdvanceTimerRef = useRef<number | null>(null);
  // Detect natural end-of-track in the SDK player_state_changed listener.
  // Listener is registered once inside ensureSdk; advanceRef lets it call
  // the freshest `advance` closure (which closes over current queue state).
  // expectedSpotifyIdRef = the spotify_id we last asked SDK to play. When
  // SDK reports a different track in track_window.current_track.uri, it
  // means Spotify auto-advanced into the user's REMOTE queue (the cause of
  // the position-based detection failing — natural track end seamlessly
  // transitions to whatever was cued in the user's session, no paused/0
  // state ever fires). URI mismatch is the reliable signal.
  const advanceRef = useRef<((dir: 1 | -1) => Promise<void>) | null>(null);
  const expectedSpotifyIdRef = useRef<string | null>(null);
  // Auto-advance only fires when SDK has CONFIRMED our expected track is
  // playing and THEN the URI changes. Otherwise the initial state events
  // after transferMyPlayback (which still report the user's previously-cued
  // remote-queue track) trigger an infinite advance loop.
  const playbackConfirmedRef = useRef<boolean>(false);
  const [sdkReady, setSdkReady] = useState(false);
  const [sdkError, setSdkError] = useState<SdkError | null>(null);

  const ensureSdk = useCallback(async (): Promise<void> => {
    if (sdkInitRef.current) return sdkInitRef.current;
    let resolveDeviceReady: () => void = () => {};
    const deviceReadyPromise = new Promise<void>((r) => {
      resolveDeviceReady = r;
    });
    deviceReadyRef.current = { promise: deviceReadyPromise, resolve: resolveDeviceReady };
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
        deviceReadyRef.current?.resolve();
      });
      player.addListener('not_ready', () => {
        setSdkReady(false);
      });
      player.addListener('player_state_changed', (sdkState: Spotify.PlaybackState | null) => {
        if (!sdkState) return;
        const sdkTrack = sdkState.track_window?.current_track;
        const currentUri = sdkTrack?.uri;
        const expected = expectedSpotifyIdRef.current;
        const sdkMatchesExpected =
          !!currentUri && !!expected && currentUri === `spotify:track:${expected}`;
        // Mark the expected track as confirmed once SDK reports it playing.
        // This gates the auto-advance mismatch check — we only react to
        // URI drift AFTER we've seen our requested track go live.
        if (sdkMatchesExpected && !sdkState.paused) {
          playbackConfirmedRef.current = true;
        }
        // Pick the cover URL from SDK's album.images. Only adopt it when
        // the SDK is actually playing OUR expected track — otherwise we'd
        // briefly flash whatever Spotify's remote queue auto-loaded.
        const coverFromSdk =
          sdkMatchesExpected && sdkTrack?.album?.images?.[0]?.url
            ? sdkTrack.album.images[0].url
            : null;
        setTrack((s) => ({
          current: s.current
            ? coverFromSdk && s.current.cover_url !== coverFromSdk
              ? { ...s.current, cover_url: coverFromSdk }
              : s.current
            : null,
          positionMs: sdkState.position,
          durationMs: sdkState.duration,
        }));
        queueDispatch({ type: 'STATUS', status: sdkState.paused ? 'paused' : 'playing' });
        // Auto-advance when Spotify's session played PAST our requested URI.
        // After our track ends, Spotify Connect typically loads the next
        // item from the user's remote queue (Verchiel-related leftovers).
        // Only fire AFTER we've confirmed our expected track was actually
        // playing — otherwise initial transferMyPlayback state events
        // (which report the user's pre-existing remote-queue track) cause
        // an infinite advance loop through the whole queue.
        if (
          currentUri &&
          expected &&
          !sdkMatchesExpected &&
          playbackConfirmedRef.current
        ) {
          // Reset both before advancing — advance() will set expected to
          // the next track's id, and confirmation must happen anew.
          expectedSpotifyIdRef.current = null;
          playbackConfirmedRef.current = false;
          void advanceRef.current?.(+1);
        }
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
    async (idx?: number, overrideTrack?: PlaybackTrack) => {
      await ensureSdk();
      // SDK boot completes when `connect()` resolves, but `ready` event (which
      // populates deviceIdRef) fires asynchronously after. On the first user
      // click after page load, ensureSdk may resolve before the device is
      // ready — without this wait `play()` silently bails and Spotify auto-
      // resumes whatever was previously cued in the user's session.
      if (!deviceIdRef.current && deviceReadyRef.current) {
        await deviceReadyRef.current.promise;
      }
      const player = playerRef.current;
      const deviceId = deviceIdRef.current;
      if (!player || !deviceId) return;

      // overrideTrack lets callers (e.g. undo) play a track that hasn't yet
      // been re-bound into queue.tracks — bypasses the queue lookup.
      const targetIdx = idx ?? queue.cursor;
      const track = overrideTrack ?? queue.tracks[targetIdx];
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
      expectedSpotifyIdRef.current = track.spotify_id;
      playbackConfirmedRef.current = false;
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
    // First-press path: SDK has whatever Spotify auto-resumed via
    // transferMyPlayback (the user's previously-cued track), but our queue
    // has not been told to play anything yet. Fire play() so the right URI
    // lands instead of resuming Spotify's stale state.
    if (queue.status === 'idle' || queue.status === 'ended') {
      await play();
      return;
    }
    await playerRef.current?.togglePlay();
  }, [ensureSdk, queue.status, play]);

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
      expectedSpotifyIdRef.current = t.spotify_id;
      playbackConfirmedRef.current = false;
      await spotifyApi.play(
        { uris: [`spotify:track:${t.spotify_id}`], deviceId },
        { onAuthExpired },
      );
    },
    [queue.cursor, queue.tracks, onAuthExpired],
  );

  const next = useCallback(() => advance(+1), [advance]);
  const prev = useCallback(() => advance(-1), [advance]);

  // Keep the SDK listener (registered once in ensureSdk) able to call the
  // freshest advance closure as queue.tracks/cursor change.
  useEffect(() => {
    advanceRef.current = advance;
  }, [advance]);

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
    expectedSpotifyIdRef.current = null;
    playbackConfirmedRef.current = false;
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
