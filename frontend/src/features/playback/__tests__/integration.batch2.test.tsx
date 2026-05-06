// frontend/src/features/playback/__tests__/integration.batch2.test.tsx
//
// F6 PlayerCard integration tests batch 2.
//
// Exercises the F5/F6 keyboard surface end-to-end: end-of-bucket transition,
// J/K cursor swap, Space play/pause, A-G seek-to-percent, Shift+J/K relative
// seek with clamping. Mounts the REAL PlaybackProvider + curate route tree via
// the shared `renderApp` harness, mocks the Spotify Web Playback SDK, and uses
// MSW to capture Spotify Web API + F5 backend traffic.
//
// Coverage:
//    5. End of bucket — assigning the last track in a single-track bucket
//       drains the queue, EndOfQueue mounts and pauses the SDK, and the
//       "Bucket finished." copy is in the DOM.
//   11. F5 hotkey swap — `K` advances cursor (playback.next → /play tracks[1]),
//       `J` rewinds (playback.prev → /play tracks[0]), digits still trigger an
//       F5 move on the backend.
//   12. Space play/pause — Space dispatches togglePlay on the SDK; no Spotify
//       Web API call (togglePlay is SDK-only).
//   13. A/S/D/F/G seek — keys map to 0% / 20% / 40% / 60% / 80% of duration;
//       SDK.seek receives the right ms value.
//   14. Shift+J / Shift+K seek — ±10s relative with clamping at 0 and
//       durationMs boundaries.
//
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor, act, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../../../test/setup';
import {
  installSpotifySdkMock,
  uninstallSpotifySdkMock,
  type FakeSpotifyPlayer,
} from '../../../test/spotifySdk';
import { __resetSdkLoaderForTests } from '../lib/sdkLoader';
import { renderApp } from '../../../test/renderApp';

/* ---------- backend fixtures ---------- */

interface FixtureTrack {
  id: string;
  spotifyId: string | null;
}

function buildBlock(srcCount: number) {
  return {
    id: 'b1',
    style_id: 's1',
    style_name: 'Tech House',
    name: 'TH W17',
    date_from: '2026-04-21',
    date_to: '2026-04-27',
    status: 'IN_PROGRESS' as const,
    created_at: '2026-04-20T00:00:00Z',
    updated_at: '2026-04-20T00:00:00Z',
    finalized_at: null,
    buckets: [
      { id: 'src', bucket_type: 'NEW' as const, inactive: false, track_count: srcCount },
      {
        id: 'dst1',
        bucket_type: 'STAGING' as const,
        inactive: false,
        track_count: 0,
        category_id: 'c1',
        category_name: 'Big Room',
      },
      {
        id: 'dst2',
        bucket_type: 'STAGING' as const,
        inactive: false,
        track_count: 0,
        category_id: 'c2',
        category_name: 'Hard Techno',
      },
      { id: 'b-old', bucket_type: 'OLD' as const, inactive: false, track_count: 0 },
      { id: 'b-disc', bucket_type: 'DISCARD' as const, inactive: false, track_count: 0 },
    ],
  };
}

function buildTracks(items: FixtureTrack[], lengthMs = 360000) {
  return {
    items: items.map((t) => ({
      track_id: t.id,
      title: `Track ${t.id}`,
      mix_name: null,
      isrc: null,
      bpm: 124,
      length_ms: lengthMs,
      publish_date: '2026-04-15',
      spotify_release_date: '2026-04-15',
      spotify_id: t.spotifyId,
      release_type: 'single',
      is_ai_suspected: false,
      artists: ['Artist A'],
      label_name: 'Label X',
      added_at: '2026-04-21T00:00:00Z',
    })),
    total: items.length,
    limit: 50,
    offset: 0,
  };
}

interface ServerCaptures {
  playCalls: Array<{ uris: string[] }>;
  transferCalls: number;
  moveCalls: number;
}

function installHandlers(
  fixtures: FixtureTrack[],
  captures: ServerCaptures,
  lengthMs = 360000,
): void {
  server.use(
    // ---- F5 backend ----
    http.get('http://localhost/triage/blocks/b1', () =>
      HttpResponse.json(buildBlock(fixtures.length)),
    ),
    http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
      HttpResponse.json(buildTracks(fixtures, lengthMs)),
    ),
    http.post('http://localhost/triage/blocks/b1/move', async () => {
      captures.moveCalls += 1;
      return HttpResponse.json({ moved: 1, correlation_id: `cid-${captures.moveCalls}` });
    }),
    // ---- Spotify Web API ----
    http.put('https://api.spotify.com/v1/me/player', () => {
      captures.transferCalls += 1;
      return HttpResponse.json({}, { status: 204 });
    }),
    http.put('https://api.spotify.com/v1/me/player/play', async ({ request }) => {
      const body = (await request.json().catch(() => ({}))) as { uris?: string[] };
      captures.playCalls.push({ uris: body.uris ?? [] });
      return HttpResponse.json({}, { status: 204 });
    }),
  );
}

/** Emit ready inside an `act()` so PlaybackProvider records deviceId. */
function emitReady(player: FakeSpotifyPlayer | null, deviceId = 'dev-1'): void {
  player?.__emit('ready', { device_id: deviceId });
}

/** Emit a player_state_changed payload. Use to populate position/duration. */
function emitPlayerState(
  player: FakeSpotifyPlayer | null,
  state: { position: number; duration: number; paused?: boolean },
): void {
  player?.__emit('player_state_changed', {
    position: state.position,
    duration: state.duration,
    paused: state.paused ?? false,
  });
}

/**
 * F6: CurateCard only renders on mobile (and has no Play button there). On
 * desktop the PlayerCard absorbs the title. Scope by curate-session.
 */
async function waitForCurateCardTrack(title: string): Promise<void> {
  await waitFor(() => {
    const session = screen.getByTestId('curate-session');
    expect(within(session).getByText(title)).toBeInTheDocument();
  });
}

function findPlayButton(): HTMLElement {
  const candidates = screen.getAllByRole('button', { name: /^play$/i });
  const enabled = candidates.find(
    (el) => !(el as HTMLButtonElement).disabled,
  );
  if (!enabled) {
    throw new Error('No enabled Play button found in current DOM');
  }
  return enabled;
}

/**
 * Pre-warm: click PlayerCard's Play button (the only Play affordance now —
 * CurateCard's button was removed in F6). Emit `ready` while the click
 * handler is awaiting deviceReadyRef so play() resolves and /play fires.
 */
async function preWarm(
  user: ReturnType<typeof userEvent.setup>,
  handle: ReturnType<typeof installSpotifySdkMock>,
  captures: ServerCaptures,
): Promise<FakeSpotifyPlayer> {
  const playBtn = findPlayButton();
  const clickPromise = user.click(playBtn);
  await waitFor(() => expect(handle.getLatest()).not.toBeNull());
  await act(async () => emitReady(handle.getLatest()));
  await clickPromise;
  await waitFor(() => expect(captures.playCalls.length).toBeGreaterThanOrEqual(1));
  return handle.getLatest()!;
}

/* ---------- suite ---------- */

describe('F6 integration · batch 2', () => {
  let captures: ServerCaptures;

  beforeEach(() => {
    captures = { playCalls: [], transferCalls: 0, moveCalls: 0 };
    __resetSdkLoaderForTests();
    document.head.querySelectorAll('script[data-spotify-sdk]').forEach((s) => s.remove());
  });

  afterEach(() => {
    uninstallSpotifySdkMock();
    __resetSdkLoaderForTests();
    document.head.querySelectorAll('script[data-spotify-sdk]').forEach((s) => s.remove());
    vi.useRealTimers();
  });

  /**
   * Scenario 5: End of bucket.
   *
   * Single-track source bucket. User plays t1, presses '1' to assign to dst1.
   * After 200ms the optimistic shrink has emptied the queue → CurateSession
   * status flips to 'empty' → EndOfQueue mounts. EndOfQueue's useEffect calls
   * playback.controls.pause() which resolves to playerRef.current?.pause() on
   * the SDK fake. Verify SDK pause was called and the i18n copy is in the DOM.
   */
  it('5. end of bucket → SDK pause + EndOfQueue UI shown', async () => {
    installHandlers([{ id: 't1', spotifyId: 'spA' }], captures);
    const handle = installSpotifySdkMock();
    const user = userEvent.setup();
    renderApp({ initialEntries: ['/curate/s1/b1/src'] });

    await waitForCurateCardTrack('Track t1');
    const player = await preWarm(user, handle, captures);

    // Assign t1 → optimistic shrink empties the queue.
    await user.keyboard('1');

    // Past the 200ms scheduleAdvance window so reducer ADVANCE + play() ran.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 250));
    });

    // EndOfQueue's i18n copy: "Bucket finished."
    await waitFor(() => {
      expect(screen.getByText(/bucket finished\./i)).toBeInTheDocument();
    });

    // EndOfQueue's useEffect calls playback.controls.pause() → SDK pause.
    await waitFor(() => {
      expect(player.pause).toHaveBeenCalled();
    });

    // Sanity: F5 backend got the move.
    expect(captures.moveCalls).toBe(1);
  }, 10000);

  /**
   * Scenario 11: F5 hotkey swap (J=prev / K=next) + digits still move tracks.
   *
   * After F6-5, J/K drive playback (NOT the curate cursor) — useCurateHotkeys
   * dispatches PREV/SKIP on the local cursor while usePlaybackHotkeys triggers
   * playback.controls.prev/next. Both run on each event; verify the playback
   * leg by inspecting Spotify Web API /play call URIs.
   *
   * After pre-warm, queue cursor is 0 (track t1 / spA). Press 'k' → playback
   * advance(+1) plays spB. Press 'j' twice → advance(-1); cursor was synced to 1
   * by the previous K, so first J should land back on spA.
   *
   * Digit '1' fires an F5 destination assign — verify by waiting on /move.
   */
  it('11. K=next → /play tracks[1]; J=prev → /play tracks[0]; digit still moves', async () => {
    installHandlers(
      [
        { id: 't1', spotifyId: 'spA' },
        { id: 't2', spotifyId: 'spB' },
        { id: 't3', spotifyId: 'spC' },
      ],
      captures,
    );
    const handle = installSpotifySdkMock();
    const user = userEvent.setup();
    renderApp({ initialEntries: ['/curate/s1/b1/src'] });

    await waitForCurateCardTrack('Track t1');
    await preWarm(user, handle, captures);
    const beforeKJ = captures.playCalls.length;

    // K → playback.next → SDK advance(+1) → /play with spB URI.
    await user.keyboard('k');
    await waitFor(() => {
      expect(captures.playCalls.length).toBeGreaterThan(beforeKJ);
    });
    expect(captures.playCalls[captures.playCalls.length - 1]?.uris).toEqual([
      'spotify:track:spB',
    ]);
    const afterK = captures.playCalls.length;

    // J → playback.prev → SDK advance(-1) → /play with spA URI.
    await user.keyboard('j');
    await waitFor(() => {
      expect(captures.playCalls.length).toBeGreaterThan(afterK);
    });
    expect(captures.playCalls[captures.playCalls.length - 1]?.uris).toEqual([
      'spotify:track:spA',
    ]);

    // Digit '1' still triggers an F5 move via useCurateHotkeys.
    const movesBefore = captures.moveCalls;
    await user.keyboard('1');
    await waitFor(() => {
      expect(captures.moveCalls).toBeGreaterThan(movesBefore);
    });
  }, 15000);

  /**
   * Scenario 12: Space play/pause → SDK togglePlay.
   *
   * usePlaybackHotkeys binds Space to playback.controls.togglePlayPause, which
   * resolves to playerRef.current?.togglePlay() on the SDK fake. Verify the
   * mock was called. No Spotify Web API /play call is expected — togglePlay
   * is SDK-only.
   */
  it('12. Space → SDK togglePlay (no Web API /play)', async () => {
    installHandlers(
      [
        { id: 't1', spotifyId: 'spA' },
        { id: 't2', spotifyId: 'spB' },
      ],
      captures,
    );
    const handle = installSpotifySdkMock();
    const user = userEvent.setup();
    renderApp({ initialEntries: ['/curate/s1/b1/src'] });

    await waitForCurateCardTrack('Track t1');
    const player = await preWarm(user, handle, captures);
    const playCallsBefore = captures.playCalls.length;

    // Emit player_state_changed so the UI reflects "playing" — not strictly
    // required for togglePlay, but mirrors the real flow and keeps the
    // PlayerCard happy.
    await act(async () => {
      emitPlayerState(player, { position: 5_000, duration: 360_000, paused: false });
    });

    // Space → SDK togglePlay.
    await user.keyboard(' ');
    await waitFor(() => {
      expect(player.togglePlay).toHaveBeenCalled();
    });

    // No additional Spotify Web API /play call — togglePlay is SDK-only.
    expect(captures.playCalls.length).toBe(playCallsBefore);
  }, 10000);

  /**
   * Scenario 13: A/S/D/F/G seek to 0/20/40/60/80%.
   *
   * Track duration 360_000ms (set in fixture). Pre-warm + emit
   * player_state_changed with duration=360_000 so PlaybackProvider has the
   * duration in state. Then verify each letter calls SDK.seek with the right
   * ms value:  A→0, S→72_000, D→144_000, F→216_000, G→288_000.
   */
  it('13. A/S/D/F/G map to SDK.seek(0/20/40/60/80% of duration)', async () => {
    installHandlers(
      [
        { id: 't1', spotifyId: 'spA' },
        { id: 't2', spotifyId: 'spB' },
      ],
      captures,
    );
    const handle = installSpotifySdkMock();
    const user = userEvent.setup();
    renderApp({ initialEntries: ['/curate/s1/b1/src'] });

    await waitForCurateCardTrack('Track t1');
    const player = await preWarm(user, handle, captures);

    // Seed positionMs / durationMs.
    await act(async () => {
      emitPlayerState(player, { position: 0, duration: 360_000, paused: false });
    });

    // D = 40% → 144_000ms.
    await user.keyboard('d');
    await waitFor(() => {
      expect(player.seek).toHaveBeenCalledWith(144_000);
    });

    // A = 0% → 0ms.
    await user.keyboard('a');
    await waitFor(() => {
      expect(player.seek).toHaveBeenCalledWith(0);
    });

    // G = 80% → 288_000ms.
    await user.keyboard('g');
    await waitFor(() => {
      expect(player.seek).toHaveBeenCalledWith(288_000);
    });

    // S = 20% → 72_000ms.
    await user.keyboard('s');
    await waitFor(() => {
      expect(player.seek).toHaveBeenCalledWith(72_000);
    });

    // F = 60% → 216_000ms.
    await user.keyboard('f');
    await waitFor(() => {
      expect(player.seek).toHaveBeenCalledWith(216_000);
    });
  }, 15000);

  /**
   * Scenario 14: Shift+J = -10s, Shift+K = +10s (with clamping).
   *
   * usePlaybackHotkeys' onSeekRelative uses event.code 'KeyJ' / 'KeyK' with
   * shiftKey true. CurateSession wires onSeekRelative to seekMs(positionMs +
   * delta). PlaybackProvider's seekMs clamps the value to [0, durationMs].
   * Drive the keys via window.dispatchEvent — userEvent's shift modifier
   * doesn't reliably set event.code on the produced KeyboardEvent.
   *
   * Mid: position 100_000ms, duration 360_000ms.
   *   Shift+J → seek(90_000)
   *   Shift+K → seek(110_000)
   *
   * Edge clamping:
   *   position 0      → Shift+J → seek(0)
   *   position 360000 → Shift+K → seek(360000)
   */
  it('14. Shift+J/K seek ±10s with clamp at 0 / duration', async () => {
    installHandlers(
      [
        { id: 't1', spotifyId: 'spA' },
        { id: 't2', spotifyId: 'spB' },
      ],
      captures,
    );
    const handle = installSpotifySdkMock();
    const user = userEvent.setup();
    renderApp({ initialEntries: ['/curate/s1/b1/src'] });

    await waitForCurateCardTrack('Track t1');
    const player = await preWarm(user, handle, captures);

    // Mid-track position.
    await act(async () => {
      emitPlayerState(player, { position: 100_000, duration: 360_000, paused: false });
    });

    // Shift+J → -10s → seek(90_000).
    await act(async () => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { code: 'KeyJ', shiftKey: true, bubbles: true }),
      );
    });
    await waitFor(() => {
      expect(player.seek).toHaveBeenCalledWith(90_000);
    });

    // Shift+K → +10s → seek(110_000).
    await act(async () => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { code: 'KeyK', shiftKey: true, bubbles: true }),
      );
    });
    await waitFor(() => {
      expect(player.seek).toHaveBeenCalledWith(110_000);
    });

    // Edge: position at 0 → Shift+J clamps to 0.
    await act(async () => {
      emitPlayerState(player, { position: 0, duration: 360_000, paused: false });
    });
    player.seek.mockClear();
    await act(async () => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { code: 'KeyJ', shiftKey: true, bubbles: true }),
      );
    });
    await waitFor(() => {
      expect(player.seek).toHaveBeenCalledWith(0);
    });

    // Edge: position at duration → Shift+K clamps to durationMs.
    await act(async () => {
      emitPlayerState(player, { position: 360_000, duration: 360_000, paused: false });
    });
    player.seek.mockClear();
    await act(async () => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { code: 'KeyK', shiftKey: true, bubbles: true }),
      );
    });
    await waitFor(() => {
      expect(player.seek).toHaveBeenCalledWith(360_000);
    });

    // suppress no-op linter — userEvent is set up but unused in this scenario.
    void user;
  }, 15000);
});
