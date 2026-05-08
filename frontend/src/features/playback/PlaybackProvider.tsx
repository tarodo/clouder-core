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
import type { SpotifyDevice } from './lib/deviceTypes';
import { lastDeviceStore } from './lib/lastDeviceStore';
import { usePolling } from './lib/usePolling';

export interface DevicesSlice {
  list: readonly SpotifyDevice[];
  active: SpotifyDevice | null;
  cloderTabId: string | null;
  isLoading: boolean;
  error: 'network' | 'auth' | null;
  isOpen: boolean;
  pickerAnchor: HTMLElement | null;
  open: (anchor?: HTMLElement | null) => void;
  close: () => void;
  refresh: () => Promise<void>;
  pick: (deviceId: string) => Promise<void>;
}

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
    /**
     * Pre-warm: load the Spotify SDK script + connect ahead of the first
     * user click. Calling on Curate route mount means by the time the user
     * clicks Play, ensureSdk + the 'ready' event have already fired and
     * `activateElement()` runs inside the user-gesture window (browser
     * autoplay policy). Idempotent.
     */
    prewarm: () => Promise<void>;
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
  devices: DevicesSlice;
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
        cloderTabIdRef.current = device_id;
        setCloderTabId(device_id);
        setSdkReady(true);
        // SYNC: assign CLOUDER tab as active and resolve deviceReadyRef so
        // play() called from a user-click doesn't await. Awaiting any
        // bootstrap work breaks the SDK activateElement() user-activation
        // chain — audio stays locked and SDK fires playback_error.
        setActive(device_id);
        void spotifyApi
          .transferMyPlayback({ deviceId: device_id, play: false }, { onAuthExpired })
          .catch(() => {
            // ignore — SDK state events will surface real errors.
          });
        deviceReadyRef.current?.resolve();

        // ASYNC: populate picker's devices list. last_device_id auto-
        // restore was removed — browser SDK device_ids change every
        // session, so a saved id is usually stale, and the second
        // transferMyPlayback (sync→CLOUDER then async→last) caused
        // Spotify Connect state_conflict that broke playback control. The
        // user picks a non-CLOUDER device explicitly via the F7 picker
        // when they want it.
        void (async () => {
          try {
            const list = await spotifyApi.getMyDevices({ onAuthExpired });
            setDevicesList(list);
            setDevicesError(null);
          } catch {
            // ignore — picker shows empty list; user re-opens to retry.
          }
        })();
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
        // Use SDK album cover when SDK URI matches the track currently in
        // state. Earlier the gate used `expectedSpotifyIdRef`, but that ref
        // gets reset by auto-advance and during transitions, so cover
        // updates were silently dropped on second/third tracks. Matching
        // against `s.current.spotify_id` instead is robust.
        // Position/duration: prefer SDK values when present, else keep what
        // play()/advance() seeded from backend so seek works even when SDK
        // is observer-only (active device ≠ CLOUDER tab).
        setTrack((s) => {
          const matchesCurrent =
            !!currentUri && !!s.current && currentUri === `spotify:track:${s.current.spotify_id}`;
          const coverFromSdk =
            matchesCurrent && sdkTrack?.album?.images?.[0]?.url
              ? sdkTrack.album.images[0].url
              : null;
          return {
            current: s.current
              ? coverFromSdk && s.current.cover_url !== coverFromSdk
                ? { ...s.current, cover_url: coverFromSdk }
                : s.current
              : null,
            positionMs: sdkState.position,
            durationMs: sdkState.duration > 0 ? sdkState.duration : s.durationMs,
          };
        });
        // queue.status from SDK is reliable only when SDK is the active
        // device. On remote the SDK pauses itself on losing play_token and
        // emits paused=true even though audio is playing on remote. We
        // manage status explicitly in pickDevice / pause / togglePlayPause.
        {
          const activeIdNow = activeDeviceIdRef.current;
          const cloderIdNow = cloderTabIdRef.current;
          if (!activeIdNow || !cloderIdNow || activeIdNow === cloderIdNow) {
            queueDispatch({ type: 'STATUS', status: sdkState.paused ? 'paused' : 'playing' });
          }
        }
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
        // Suppress when active device is remote — SDK is observer-only and
        // these errors are expected (it can't control inactive playback).
        // Real errors on remote surface from Web API calls (pause/resume/seek).
        const activeId = activeDeviceIdRef.current;
        const cloderId = cloderTabIdRef.current;
        if (activeId && cloderId && activeId !== cloderId) return;
        setSdkError({ kind: 'playback', message });
        queueDispatch({ type: 'STATUS', status: 'error' });
      });
      await player.connect();
    })();
    return sdkInitRef.current;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, navigate]);

  const play = useCallback(
    async (idx?: number, overrideTrack?: PlaybackTrack) => {
      await ensureSdk();
      // SDK boot completes when `connect()` resolves, but `ready` event (which
      // populates activeDeviceIdRef) fires asynchronously after. On the first
      // user click after page load, ensureSdk may resolve before the device is
      // ready — without this wait `play()` silently bails and Spotify auto-
      // resumes whatever was previously cued in the user's session.
      if (!activeDeviceIdRef.current && deviceReadyRef.current) {
        await deviceReadyRef.current.promise;
      }
      const player = playerRef.current;
      const deviceId = activeDeviceIdRef.current;
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
      // Source-of-truth `track.current` comes from the queue cursor at play
      // time. Seed `durationMs` from backend (track.duration_ms) and reset
      // `positionMs` so seek hotkeys (A/S/D/F/G) work even when the SDK is
      // in observer mode (active device ≠ CLOUDER tab — SDK stops emitting
      // `player_state_changed` and durationMs would otherwise stay stale).
      setTrack(() => ({
        current: track,
        durationMs: track.duration_ms || 0,
        positionMs: 0,
      }));
      queueDispatch({ type: 'STATUS', status: 'loading' });
      expectedSpotifyIdRef.current = track.spotify_id;
      playbackConfirmedRef.current = false;
      await spotifyApi.play(
        { uris: [`spotify:track:${track.spotify_id}`], deviceId },
        { onAuthExpired },
      );
      // On remote (SDK observer-only) player_state_changed never fires
      // album.images, so the cover fallback can't fill in. Fetch the cover
      // from Spotify Web API and patch s.current. No-op when backend
      // already provided cover_url.
      const cloderId = cloderTabIdRef.current;
      if (deviceId !== cloderId && !track.cover_url && track.spotify_id) {
        void spotifyApi
          .getTrackCover(track.spotify_id, { onAuthExpired })
          .then((coverUrl) => {
            if (!coverUrl) return;
            setTrack((s) =>
              s.current && s.current.spotify_id === track.spotify_id && !s.current.cover_url
                ? { ...s, current: { ...s.current, cover_url: coverUrl } }
                : s,
            );
          })
          .catch(() => {});
      }
    },
    [queue.cursor, queue.tracks, ensureSdk, onAuthExpired],
  );

  const pause = useCallback(async () => {
    const activeId = activeDeviceIdRef.current;
    const cloderId = cloderTabIdRef.current;
    // SDK pause only works on the active local device. On remote (active ≠
    // CLOUDER tab) SDK is observer-only — fall through to Web API.
    if (activeId && cloderId && activeId !== cloderId) {
      await spotifyApi.pause({ deviceId: activeId }, { onAuthExpired });
      queueDispatch({ type: 'STATUS', status: 'paused' });
      return;
    }
    await playerRef.current?.pause();
  }, [onAuthExpired]);

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
    const activeId = activeDeviceIdRef.current;
    const cloderId = cloderTabIdRef.current;
    if (activeId && cloderId && activeId !== cloderId) {
      // Remote device — togglePlay on SDK is a no-op. Branch on cached
      // queue.status instead and route through Web API.
      if (queue.status === 'playing' || queue.status === 'buffering') {
        await spotifyApi.pause({ deviceId: activeId }, { onAuthExpired });
        queueDispatch({ type: 'STATUS', status: 'paused' });
      } else {
        await spotifyApi.resume({ deviceId: activeId }, { onAuthExpired });
        queueDispatch({ type: 'STATUS', status: 'playing' });
      }
      return;
    }
    await playerRef.current?.togglePlay();
  }, [ensureSdk, queue.status, play, onAuthExpired]);

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
      const deviceId = activeDeviceIdRef.current;
      if (!t || !t.spotify_id || !deviceId) return;
      // Mirror play() — backend-seeded duration so seek works in observer
      // mode (active device ≠ CLOUDER tab) where SDK state events stop.
      setTrack(() => ({
        current: t,
        durationMs: t.duration_ms || 0,
        positionMs: 0,
      }));
      expectedSpotifyIdRef.current = t.spotify_id;
      playbackConfirmedRef.current = false;
      await spotifyApi.play(
        { uris: [`spotify:track:${t.spotify_id}`], deviceId },
        { onAuthExpired },
      );
      // Remote-cover fallback (mirror of play() — SDK observer doesn't
      // fire album.images on remote). No-op when backend already had it.
      const cloderId = cloderTabIdRef.current;
      if (deviceId !== cloderId && !t.cover_url && t.spotify_id) {
        const trackId = t.spotify_id;
        void spotifyApi
          .getTrackCover(trackId, { onAuthExpired })
          .then((coverUrl) => {
            if (!coverUrl) return;
            setTrack((s) =>
              s.current && s.current.spotify_id === trackId && !s.current.cover_url
                ? { ...s, current: { ...s.current, cover_url: coverUrl } }
                : s,
            );
          })
          .catch(() => {});
      }
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
      const activeId = activeDeviceIdRef.current;
      const cloderId = cloderTabIdRef.current;
      // When active device is the CLOUDER Web Player tab, SDK seek is the
      // fastest path. When user has picked a remote device (phone, speaker
      // etc.), SDK is observer-only and `player.seek` is a no-op — fall
      // through to Spotify Web API which targets the active device.
      if (activeId && cloderId && activeId !== cloderId) {
        await spotifyApi.seek({ positionMs: clamped, deviceId: activeId }, { onAuthExpired });
        // SDK won't emit player_state_changed for remote devices, mirror
        // the new position locally so the scrub bar reflects the seek.
        setTrack((s) => ({ ...s, positionMs: clamped }));
        return;
      }
      await playerRef.current?.seek(clamped);
    },
    [track.durationMs, onAuthExpired],
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

  // --- Devices slice (stub — real logic lands in Tasks 6–9) ---
  const [devicesList, setDevicesList] = useState<readonly SpotifyDevice[]>([]);
  const [activeDeviceId, setActiveDeviceId] = useState<string | null>(null);
  const [cloderTabId, setCloderTabId] = useState<string | null>(null);
  const [devicesLoading, setDevicesLoading] = useState(false);
  const [devicesError, setDevicesError] = useState<'network' | 'auth' | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerAnchor, setPickerAnchor] = useState<HTMLElement | null>(null);

  const activeDeviceIdRef = useRef<string | null>(null);
  const cloderTabIdRef = useRef<string | null>(null);

  const setActive = useCallback((deviceId: string | null) => {
    activeDeviceIdRef.current = deviceId;
    setActiveDeviceId(deviceId);
  }, []);

  const openPicker = useCallback((anchor?: HTMLElement | null) => {
    setPickerAnchor(anchor ?? null);
    setPickerOpen(true);
  }, []);

  const closePicker = useCallback(() => {
    setPickerOpen(false);
    setPickerAnchor(null); // avoid stale HTMLElement ref
  }, []);

  const refreshDevices = useCallback(async (): Promise<void> => {
    setDevicesLoading(true);
    try {
      const list = await spotifyApi.getMyDevices({ onAuthExpired });
      setDevicesList(list);
      setDevicesError(null);
      // Active-device-offline detection: if the active device disappeared
      // from the new list, flip queue.status to 'disconnected'. The user
      // recovers by opening the picker and choosing another device.
      const activeId = activeDeviceIdRef.current;
      if (activeId && !list.some((d) => d.id === activeId)) {
        queueDispatch({ type: 'STATUS', status: 'disconnected' });
      }
    } catch {
      setDevicesError('network');
    } finally {
      setDevicesLoading(false);
    }
  }, [onAuthExpired]);

  const pickDevice = useCallback(async (deviceId: string): Promise<void> => {
    try {
      // play: true keeps audio going on the new device when the user
      // switches mid-playback. Spotify treats it as "ensure playback
      // happens" — if there is nothing to play, it is a no-op.
      await spotifyApi.transferMyPlayback({ deviceId, play: true }, { onAuthExpired });
      setActive(deviceId);
      lastDeviceStore.set(deviceId);
      setPickerOpen(false);
      setPickerAnchor(null);
      // After transferMyPlayback({play:true}), Spotify resumes playback on
      // the new device. SDK on the CLOUDER tab is now observer-only and
      // its paused=true state events should not override our authoritative
      // status (gated in player_state_changed listener). Set 'playing'
      // explicitly so togglePlayPause's status-branch routes to pause API.
      const cloderId = cloderTabIdRef.current;
      if (cloderId && deviceId !== cloderId) {
        queueDispatch({ type: 'STATUS', status: 'playing' });
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : '';
      if (message.includes('spotify_api_404')) {
        // Device went offline between poll and tap. Refresh and keep picker open.
        void refreshDevices();
      }
      // 5xx: surface via toast in caller (UI layer); leave picker open.
      throw err;
    }
  }, [onAuthExpired, refreshDevices, setActive]);

  const activeDevice = useMemo(
    () => devicesList.find((d) => d.id === activeDeviceId) ?? null,
    [devicesList, activeDeviceId],
  );

  // Poll getMyDevices every 30s (picker closed) or 5s (picker open).
  // Also fires on window 'focus' events (handled inside usePolling).
  usePolling(refreshDevices, {
    enabled: sdkReady,
    intervalMs: pickerOpen ? 5000 : 30000,
  });
  // --- End devices slice ---

  const value = useMemo<PlaybackContextValue>(
    () => ({
      queue,
      track,
      sdk: { ready: sdkReady, error: sdkError },
      controls: {
        prewarm: ensureSdk,
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
      devices: {
        list: devicesList,
        active: activeDevice,
        cloderTabId,
        isLoading: devicesLoading,
        error: devicesError,
        isOpen: pickerOpen,
        pickerAnchor,
        open: openPicker,
        close: closePicker,
        refresh: refreshDevices,
        pick: pickDevice,
      },
    }),
    [
      queue,
      track,
      sdkReady,
      sdkError,
      ensureSdk,
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
      devicesList,
      activeDevice,
      cloderTabId,
      devicesLoading,
      devicesError,
      pickerOpen,
      pickerAnchor,
      openPicker,
      closePicker,
      refreshDevices,
      pickDevice,
    ],
  );

  return <PlaybackContext.Provider value={value}>{children}</PlaybackContext.Provider>;
}
