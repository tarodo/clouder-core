// frontend/src/features/playback/__tests__/integration.batch3.test.tsx
//
// F6 PlayerCard integration tests batch 3.
//
// Exercises the route-level chrome layered around the curate session:
// MiniBar visibility on non-PlayerCard routes, LeaveContextDialog blocker
// flow, MiniBar close → clearQueue, empty-bucket PlayerCard state, and the
// SDK error → route redirect / disconnected state surfaces.
//
// Coverage:
//    8. Route nav with active queue → PlayerCard unmounts → MiniBar appears.
//    9. Leave-context confirm dialog (cancel keeps you on the current
//       session, confirm proceeds + clears the queue).
//   10. MiniBar close → queue cleared, MiniBar disappears.
//   15. Empty bucket: 100% null spotify_id → empty-bucket PlayerCard state +
//       Space hotkey is a no-op (PlaybackProvider.play short-circuits on null
//       spotify_id).
//   16. Disconnected: SDK initialization_error → PlayerCard disconnected
//       state (WifiOff icon + "Reconnect Spotify" subline).
//   17. Premium required: SDK account_error → PlaybackProvider navigate(
//       '/auth/premium-required').
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
import { renderAppWithRouter } from '../../../test/renderApp';

/* ---------- backend fixtures ---------- */

interface FixtureTrack {
  id: string;
  spotifyId: string | null;
}

function buildBlock(blockId: string, bucketCount: Record<string, number>) {
  return {
    id: blockId,
    style_id: 's1',
    style_name: 'Tech House',
    name: `TH ${blockId}`,
    date_from: '2026-04-21',
    date_to: '2026-04-27',
    status: 'IN_PROGRESS' as const,
    created_at: '2026-04-20T00:00:00Z',
    updated_at: '2026-04-20T00:00:00Z',
    finalized_at: null,
    buckets: [
      {
        id: 'src',
        bucket_type: 'NEW' as const,
        inactive: false,
        track_count: bucketCount.src ?? 0,
      },
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

interface BlockFixture {
  blockId: string;
  tracks: FixtureTrack[];
}

function installHandlers(
  blocks: BlockFixture[],
  captures: ServerCaptures,
  lengthMs = 360000,
): void {
  server.use(
    ...blocks.flatMap((b) => [
      http.get(`http://localhost/triage/blocks/${b.blockId}`, () =>
        HttpResponse.json(buildBlock(b.blockId, { src: b.tracks.length })),
      ),
      http.get(`http://localhost/triage/blocks/${b.blockId}/buckets/src/tracks`, () =>
        HttpResponse.json(buildTracks(b.tracks, lengthMs)),
      ),
      http.post(`http://localhost/triage/blocks/${b.blockId}/move`, async () => {
        captures.moveCalls += 1;
        return HttpResponse.json({ moved: 1, correlation_id: `cid-${captures.moveCalls}` });
      }),
    ]),
    // ---- Spotify Web API ----
    // F7: SDK ready handler now calls getMyDevices before transferMyPlayback.
    // Stub the devices endpoint so the bootstrap completes without an MSW
    // unhandled-request error.
    http.get('https://api.spotify.com/v1/me/player/devices', () =>
      HttpResponse.json({ devices: [{ id: 'dev-1', name: 'CLOUDER', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null }] }),
    ),
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

function emitReady(player: FakeSpotifyPlayer | null, deviceId = 'dev-1'): void {
  player?.__emit('ready', { device_id: deviceId });
}

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
 * Pre-warm: click PlayerCard's Play button (CurateCard's was removed in F6),
 * emit `ready` while the click is awaiting deviceReadyRef so play() resolves,
 * then emit player_state_changed paused=false so MiniBar visibility kicks in.
 */
async function preWarmAndPlay(
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
  const player = handle.getLatest()!;
  await act(async () => {
    emitPlayerState(player, { position: 1_000, duration: 360_000, paused: false });
  });
  return player;
}

/* ---------- suite ---------- */

describe('F6 integration · batch 3', () => {
  let captures: ServerCaptures;

  beforeEach(() => {
    captures = { playCalls: [], transferCalls: 0, moveCalls: 0 };
    __resetSdkLoaderForTests();
    document.head.querySelectorAll('script[data-spotify-sdk]').forEach((s) => s.remove());
    // Ensure MiniBar's `Open in Curate` link gets a deterministic style slug.
    try {
      localStorage.setItem('clouder.lastCurateStyle', 's1');
    } catch {
      /* ignore */
    }
  });

  afterEach(() => {
    uninstallSpotifySdkMock();
    __resetSdkLoaderForTests();
    document.head.querySelectorAll('script[data-spotify-sdk]').forEach((s) => s.remove());
    vi.useRealTimers();
    try {
      localStorage.clear();
    } catch {
      /* ignore */
    }
  });

  /**
   * Scenario 8: Route nav with active queue.
   *
   * Mount at /curate/s1/b1/src, play track 0, navigate to /tracks. PlayerCard
   * (rendered by CurateSession) unmounts when the curate route exits;
   * PlaybackChrome's MiniBar appears because hasPlayerCard('/tracks') is
   * false and queue.source !== null + queue.status === 'playing'.
   *
   * NOTE: navigation must NOT cross context boundaries (LeaveContextDialog
   * blocks curate→curate). /tracks is not a curate route, so the blocker's
   * `contextDifferent` check returns false and the navigation proceeds.
   */
  it('8. Curate playing → /tracks → PlayerCard unmounts, MiniBar appears', async () => {
    installHandlers(
      [{ blockId: 'b1', tracks: [{ id: 't1', spotifyId: 'spA' }] }],
      captures,
    );
    const handle = installSpotifySdkMock();
    const user = userEvent.setup();
    const { router } = renderAppWithRouter({ initialEntries: ['/curate/s1/b1/src'] });

    await waitForCurateCardTrack('Track t1');
    await preWarmAndPlay(user, handle, captures);

    // Sanity: PlayerCard is mounted on the curate route (data-state attr on
    // its outer Paper). F6 dropped the "Now Playing" eyebrow text.
    expect(document.querySelector('[data-state]')).not.toBeNull();
    expect(screen.getByTestId('curate-session')).toBeInTheDocument();

    // Navigate off curate → /tracks. Drive via router.navigate to bypass the
    // SPA-link click race (none expected here since contextDifferent('/tracks')
    // is false, but consistency with scenario 9 keeps the harness simple).
    await act(async () => {
      await router.navigate('/tracks');
    });

    await waitFor(() => {
      expect(screen.getByTestId('tracks-page')).toBeInTheDocument();
    });

    // PlayerCard unmounts when CurateSession does.
    expect(screen.queryByTestId('curate-session')).toBeNull();

    // MiniBar is visible — the region's accessible name is the "Now playing —
    // {{title}}" template (lower-case "Now playing", em-dash separator).
    expect(
      screen.getByRole('region', { name: /now playing — track t1/i }),
    ).toBeInTheDocument();
  }, 15000);

  /**
   * Scenario 9: Leave-context confirm dialog.
   *
   * Start at /curate/s1/b1/src playing track 0. Navigate to a different
   * curate session — /curate/s1/b2/src. LeaveContextDialog blocks the
   * navigation (contextDifferent returns true on different blockId). Cancel
   * keeps us on /curate/s1/b1/src; confirm proceeds + clears the queue.
   */
  it('9a. switch curate sessions → confirm dialog opens; cancel stays', async () => {
    installHandlers(
      [
        { blockId: 'b1', tracks: [{ id: 't1', spotifyId: 'spA' }] },
        { blockId: 'b2', tracks: [{ id: 't2', spotifyId: 'spB' }] },
      ],
      captures,
    );
    const handle = installSpotifySdkMock();
    const user = userEvent.setup();
    const { router } = renderAppWithRouter({ initialEntries: ['/curate/s1/b1/src'] });

    await waitForCurateCardTrack('Track t1');
    await preWarmAndPlay(user, handle, captures);

    // Cross-context navigation → blocker fires → dialog opens.
    void router.navigate('/curate/s1/b2/src');
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    // Cancel → blocker.reset() → dialog closes + we stay on b1's session.
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: /Нет, остаться/i }));
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull();
    });
    expect(router.state.location.pathname).toBe('/curate/s1/b1/src');
  }, 15000);

  it('9b. switch curate sessions → confirm dialog opens; confirm proceeds + clears queue', async () => {
    installHandlers(
      [
        { blockId: 'b1', tracks: [{ id: 't1', spotifyId: 'spA' }] },
        { blockId: 'b2', tracks: [{ id: 't2', spotifyId: 'spB' }] },
      ],
      captures,
    );
    const handle = installSpotifySdkMock();
    const user = userEvent.setup();
    const { router } = renderAppWithRouter({ initialEntries: ['/curate/s1/b1/src'] });

    await waitForCurateCardTrack('Track t1');
    const player = await preWarmAndPlay(user, handle, captures);

    void router.navigate('/curate/s1/b2/src');
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    // Confirm → onConfirm(clearQueue) + blocker.proceed().
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: /Да, новый блок/i }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/curate/s1/b2/src');
    });

    // clearQueue → SDK pause + queueDispatch CLEAR.
    await waitFor(() => {
      expect(player.pause).toHaveBeenCalled();
    });
  }, 15000);

  /**
   * Scenario 10: MiniBar close → clearQueue → MiniBar disappears.
   *
   * Pre-warm + play, navigate to /tracks (MiniBar mounts), click MiniBar's
   * close button. clearQueue runs → queue.status='idle' → showMini becomes
   * false → MiniBar unmounts.
   */
  it('10. MiniBar close button → clearQueue → MiniBar disappears', async () => {
    installHandlers(
      [{ blockId: 'b1', tracks: [{ id: 't1', spotifyId: 'spA' }] }],
      captures,
    );
    const handle = installSpotifySdkMock();
    const user = userEvent.setup();
    const { router } = renderAppWithRouter({ initialEntries: ['/curate/s1/b1/src'] });

    await waitForCurateCardTrack('Track t1');
    const player = await preWarmAndPlay(user, handle, captures);

    await act(async () => {
      await router.navigate('/tracks');
    });

    const minibar = await screen.findByRole('region', {
      name: /now playing — track t1/i,
    });
    const closeBtn = within(minibar).getByRole('button', { name: /close player/i });
    await user.click(closeBtn);

    await waitFor(() => {
      expect(
        screen.queryByRole('region', { name: /now playing/i }),
      ).toBeNull();
    });
    // clearQueue's pause path runs through the SDK fake.
    expect(player.pause).toHaveBeenCalled();
  }, 15000);

  /**
   * Scenario 15: Empty bucket — 100% null spotify_id.
   *
   * CurateSession derives `allNullSpotifyId` from playback.queue.tracks (the
   * post-bindQueue list). When all are null, PlayerCard renders the
   * 'empty-bucket' state (WifiOff icon + "В этом ведре нет треков" subline).
   * Space is a no-op because the SDK never gets booted (CurateCard's onPlay
   * is the only entry point and we don't click it).
   */
  it('15. all-null-spotify-id bucket → PlayerCard empty-bucket state, Space no-op', async () => {
    installHandlers(
      [
        {
          blockId: 'b1',
          tracks: [
            { id: 't1', spotifyId: null },
            { id: 't2', spotifyId: null },
          ],
        },
      ],
      captures,
    );
    const handle = installSpotifySdkMock();
    const user = userEvent.setup();
    renderAppWithRouter({ initialEntries: ['/curate/s1/b1/src'] });

    await waitForCurateCardTrack('Track t1');

    // PlayerCard's empty-bucket subline. The CurateCard separately renders
    // its own "no Spotify match" hint, so query by the body i18n string.
    await waitFor(() => {
      expect(
        screen.getByText('В этом ведре нет треков с Spotify match'),
      ).toBeInTheDocument();
    });

    // Space → usePlaybackHotkeys → playback.controls.togglePlayPause. This
    // boots the SDK lazily (ensureSdk), but no Spotify Web API /play call
    // fires because togglePlayPause is SDK-only. The empty-bucket invariant
    // we care about is: no track playback request hits the Web API since
    // every queue track has null spotify_id and play() short-circuits.
    const beforePlay = captures.playCalls.length;
    await user.keyboard(' ');
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(captures.playCalls.length).toBe(beforePlay);
    // SDK may or may not be created (togglePlay calls ensureSdk). Either way,
    // the player.togglePlay() never gets a real track URI to play.
    void handle;
  }, 10000);

  /**
   * Scenario 16: SDK initialization_error → PlayerCard disconnected state.
   *
   * Click play to boot the SDK, emit 'initialization_error'. PlaybackProvider
   * sets sdk.error = { kind: 'init', ... }. CurateSession's playerState
   * derivation maps this to 'disconnected' → PlayerCard shows the WifiOff
   * icon + "Reconnect Spotify" subline.
   */
  it('16. SDK initialization_error → PlayerCard disconnected state', async () => {
    installHandlers(
      [{ blockId: 'b1', tracks: [{ id: 't1', spotifyId: 'spA' }] }],
      captures,
    );
    const handle = installSpotifySdkMock();
    const user = userEvent.setup();
    renderAppWithRouter({ initialEntries: ['/curate/s1/b1/src'] });

    await waitForCurateCardTrack('Track t1');

    // Boot the SDK by kicking off play() — F6's deviceReadyRef makes play()
    // hang awaiting `ready`, but ensureSdk has already constructed the fake
    // Player + registered listeners. We don't await the click; the promise
    // is intentionally orphaned because we're about to error out.
    const playBtn = findPlayButton();
    user.click(playBtn).catch(() => {
      /* orphaned — error scenarios don't await the play flow */
    });

    await waitFor(() => expect(handle.getLatest()).not.toBeNull());
    const player = handle.getLatest()!;

    // Emit initialization_error → PlaybackProvider sets sdk.error kind='init'.
    await act(async () => {
      player.__emit('initialization_error', { message: 'sdk init failed' });
    });

    // PlayerCard's disconnected state: data-state="disconnected" on the
    // outer Paper. The "Reconnect Spotify" subline is split across nodes
    // (text + dot separator + Anchor link), so RTL `getByText` doesn't span
    // them — match the data attribute instead.
    await waitFor(() => {
      const paper = document.querySelector('[data-state="disconnected"]');
      expect(paper).not.toBeNull();
    });
    // The "Open device picker" Anchor button only exists on the disconnected
    // subline — assert it's present as a smoke check that the disconnected
    // copy rendered.
    expect(
      screen.getByRole('button', { name: /open device picker/i }),
    ).toBeInTheDocument();
  }, 10000);

  /**
   * Scenario 17: SDK account_error → navigate('/auth/premium-required').
   *
   * Boot the SDK, emit 'account_error'. PlaybackProvider's listener calls
   * navigate('/auth/premium-required') unconditionally. The placeholder
   * route's testid marker confirms the redirect landed.
   */
  it('17. SDK account_error → navigate /auth/premium-required', async () => {
    installHandlers(
      [{ blockId: 'b1', tracks: [{ id: 't1', spotifyId: 'spA' }] }],
      captures,
    );
    const handle = installSpotifySdkMock();
    const user = userEvent.setup();
    const { router } = renderAppWithRouter({
      initialEntries: ['/curate/s1/b1/src'],
    });

    await waitForCurateCardTrack('Track t1');

    // Boot the SDK; play() will hang on deviceReadyRef but ensureSdk already
    // registered the account_error listener.
    const playBtn = findPlayButton();
    user.click(playBtn).catch(() => {
      /* orphaned — error scenarios don't await the play flow */
    });

    await waitFor(() => expect(handle.getLatest()).not.toBeNull());
    const player = handle.getLatest()!;

    await act(async () => {
      player.__emit('account_error', { message: 'premium required' });
    });

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/auth/premium-required');
    });
    expect(screen.getByTestId('premium-required-page')).toBeInTheDocument();
  }, 10000);
});
