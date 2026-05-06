// frontend/src/features/playback/__tests__/integration.batch1.test.tsx
//
// F6 PlayerCard integration tests batch 1.
//
// Exercises the REAL PlaybackProvider mounted under the curate route tree, the
// REAL useCurateSession bindQueue + auto-advance flow, mocked Spotify SDK +
// Spotify Web API, and the F5 backend triage move endpoint.
//
// Coverage:
//   1. First Play happy path — CurateCard play button → ensureSdk → ready event
//      → device transfer → Spotify play call with correct URI.
//   2. Auto-advance after destination — assign via hotkey "1" → 200ms timer →
//      shrink-driven cursor advance → playback.controls.play() called for next
//      track.
//   3. Undo within 200ms window — assign then undo before timer fires; the
//      cancelPendingAdvance call prevents the next-track play.
//   4. Skip null spotify_id — assign first track with non-null id; next track in
//      queue has null spotify_id; PlaybackProvider.play silently no-ops on null
//      (PB4 gap — see test note).
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

/**
 * The PlayerCard center button has aria-label "Play" when state is idle/
 * paused/buffering and "Pause" when state is playing. CurateCard no longer
 * renders any Play button on F6. The PlayerCard button is therefore the
 * unambiguous "Play" target — return the enabled match.
 */
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
 * Pre-warm helper: clicks the PlayerCard Play button to trigger
 * togglePlayPause→play(), emits SDK 'ready' while the click handler is
 * awaiting deviceReadyRef, then waits for the first /play call. Returns
 * the latest fake player. After this, queue.cursor=0 and SDK is wired up.
 */
async function preWarm(
  user: ReturnType<typeof userEvent.setup>,
  handle: ReturnType<typeof installSpotifySdkMock>,
  captures: { playCalls: Array<{ uris: string[] }> },
): Promise<FakeSpotifyPlayer> {
  const playBtn = findPlayButton();
  const clickPromise = user.click(playBtn);
  await waitFor(() => expect(handle.getLatest()).not.toBeNull());
  await act(async () => {
    emitReady(handle.getLatest());
  });
  await clickPromise;
  await waitFor(() => expect(captures.playCalls.length).toBeGreaterThanOrEqual(1));
  return handle.getLatest()!;
}

/* ---------- backend fixtures ---------- */

interface FixtureTrack {
  id: string;
  spotifyId: string | null;
}

function buildBlock() {
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
      { id: 'src', bucket_type: 'NEW' as const, inactive: false, track_count: 3 },
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

function buildTracks(items: FixtureTrack[]) {
  return {
    items: items.map((t) => ({
      track_id: t.id,
      title: `Track ${t.id}`,
      mix_name: null,
      isrc: null,
      bpm: 124,
      length_ms: 360000,
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
): void {
  server.use(
    // ---- F5 backend ----
    http.get('http://localhost/triage/blocks/b1', () =>
      HttpResponse.json(buildBlock()),
    ),
    http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
      HttpResponse.json(buildTracks(fixtures)),
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

/**
 * Fire the SDK 'ready' event so PlaybackProvider records a deviceId. Must be
 * called inside `act()` after `play()` has triggered ensureSdk and the latest
 * fake player has been created.
 */
function emitReady(player: FakeSpotifyPlayer | null, deviceId = 'dev-1'): void {
  player?.__emit('ready', { device_id: deviceId });
}

/**
 * F6: CurateCard only renders on mobile (and even there has no Play button).
 * On desktop the PlayerCard absorbs the title — wait for any element with
 * the track text inside the curate-session container. The earlier scope to
 * data-testid="curate-card" no longer survives the desktop layout split.
 */
async function waitForCurateCardTrack(title: string): Promise<void> {
  await waitFor(() => {
    const session = screen.getByTestId('curate-session');
    expect(within(session).getByText(title)).toBeInTheDocument();
  });
}

/* ---------- suite ---------- */

describe('F6 integration · batch 1', () => {
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
   * Scenario 1: First Play happy path.
   *
   * Loads CurateSession, clicks the CurateCard's play button, emits SDK ready,
   * then waits for Spotify Web API /play to fire with the correct URI.
   */
  it('1. first Play happy path → ensureSdk → ready → /play with track URI', async () => {
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

    // F6: CurateCard no longer has its own Play button; the PlayerCard's
    // center button is the only Play affordance. With queue.status='idle' it
    // routes togglePlayPause → play(), which now awaits deviceReadyRef.
    // Click WITHOUT awaiting so we can emit `ready` while the click handler
    // is still in flight.
    const playBtn = findPlayButton();
    const clickPromise = user.click(playBtn);

    // ensureSdk creates a fake Player; emit ready to resolve deviceReadyRef.
    await waitFor(() => expect(handle.getLatest()).not.toBeNull());
    await act(async () => {
      emitReady(handle.getLatest());
    });
    await clickPromise;

    await waitFor(() => {
      expect(captures.playCalls.length).toBeGreaterThanOrEqual(1);
    });
    // togglePlayPause→play() (no idx) reads cursor=0 from queue → spA.
    const lastUris = captures.playCalls[captures.playCalls.length - 1]?.uris;
    expect(lastUris).toEqual(['spotify:track:spA']);
  });

  /**
   * Scenario 2: Auto-advance after destination.
   *
   * Pre-warm SDK by clicking play, emit ready, assign track via hotkey "1",
   * wait 220ms for the pending-advance timer, then verify a SECOND /play call
   * fired with the next track's URI.
   *
   * Note: the F5 optimistic shrink removes track 1 from the cache, so after
   * advance the cursor=0 of the shrunken queue is track 2 (spB).
   */
  it('2. auto-advance after destination plays next track', async () => {
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
    // Capture pre-advance state
    const beforeAdvanceCalls = captures.playCalls.length;

    // Assign track t1 via destination hotkey 1.
    await user.keyboard('1');

    // Advance pending timers (200ms in scheduleAdvance).
    await act(async () => {
      await new Promise((r) => setTimeout(r, 250));
    });

    // After shrink, cursor=0 of queue=[t2,t3]; advance fires play() (no arg)
    // → reads bound cursor from the post-shrink queue = spB.
    await waitFor(() => {
      expect(captures.playCalls.length).toBeGreaterThan(beforeAdvanceCalls);
    });
    const lastUris = captures.playCalls[captures.playCalls.length - 1]?.uris;
    expect(lastUris).toEqual(['spotify:track:spB']);

    // Sanity: assign actually moved the track on the backend.
    expect(captures.moveCalls).toBeGreaterThanOrEqual(1);
  }, 10000);

  /**
   * Scenario 3: Undo within 200ms window.
   *
   * Press "1" then "U" before the 200ms scheduleAdvance fires; verify NO
   * additional /play calls fire after the pre-warm phase. useCurateSession.undo
   * calls playback.controls.cancelPendingAdvance + clears its own pending
   * timer, so the post-advance play() never runs.
   */
  it('3. undo within 200ms window cancels pending playback advance', async () => {
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
    const beforeUndoCalls = captures.playCalls.length;

    // Assign + undo within window (no setTimeout pause between them).
    await user.keyboard('1');
    await user.keyboard('u');

    // Wait past the 200ms threshold to ensure no advance fires.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 300));
    });

    // No additional /play calls beyond the pre-warm phase.
    expect(captures.playCalls.length).toBe(beforeUndoCalls);
    // Track t1 should be visible again post-undo (snapshot restored).
    await waitForCurateCardTrack('Track t1');
  }, 10000);

  /**
   * Scenario 4: Skip null spotify_id (post-advance behaviour).
   *
   * Queue: t1 spA, t2 null, t3 spC. After assigning t1 + 220ms advance, the
   * shrunken queue is [t2(null), t3(spC)]. PlaybackProvider.play (no arg) reads
   * cursor=0 → t2 has null spotify_id → silent no-op.
   *
   * KNOWN GAP (PB4): scheduleAdvance calls play() not next(); play() does NOT
   * skip null tracks (it returns silently). next() WOULD skip via
   * findNextPlayable. Until the helper is wired into the pending-advance path,
   * we assert the CURRENT behaviour: a null next track produces no /play call.
   *
   * This codifies the gap so the test flips to "expect spC" once the fix lands.
   */
  it('4. skip null spotify_id — current behaviour: pending advance silently no-ops', async () => {
    installHandlers(
      [
        { id: 't1', spotifyId: 'spA' },
        { id: 't2', spotifyId: null },
        { id: 't3', spotifyId: 'spC' },
      ],
      captures,
    );
    const handle = installSpotifySdkMock();
    const user = userEvent.setup();
    renderApp({ initialEntries: ['/curate/s1/b1/src'] });

    await waitForCurateCardTrack('Track t1');

    await preWarm(user, handle, captures);
    const beforeAdvanceCalls = captures.playCalls.length;

    await user.keyboard('1');
    await act(async () => {
      await new Promise((r) => setTimeout(r, 250));
    });

    // PB4 gap: play() with null spotify_id returns silently — no /play call.
    // Move call still happened on the backend.
    expect(captures.playCalls.length).toBe(beforeAdvanceCalls);
    expect(captures.moveCalls).toBeGreaterThanOrEqual(1);
    // TODO(PB4): when scheduleAdvance is migrated to next() / findNextPlayable,
    // expect lastUris to equal ['spotify:track:spC'] instead.
  }, 10000);
});
