# Demo on sample data

**Live:** <https://tarodo.github.io/clouder-core/demo/> — the real SPA, no login, no AWS.

The production app sits behind a Spotify allow-list. The demo build runs the same code against an
API that lives in the browser: [MSW](https://mswjs.io) answers every request from an in-memory
sample catalog.

## How it works

- `vite --mode demo` (`pnpm dev:demo`, `pnpm build:demo`) serves the app under
  `/clouder-core/demo/` and adds the MSW worker (`msw init demo-public`, generated, not committed).
- `src/main.tsx` starts the worker (`src/demo/start.ts`) before React mounts, because
  `AuthProvider` calls `/auth/refresh` on mount. The production build drops this branch, so its
  bundle contains no demo code (the PR checks that the `pnpm build` output has no MSW worker code).
- `src/demo/seed.ts` builds the catalog: two invented styles (Melodic House & Techno, Afro House), each with a finalized and an open
  triage week, three categories, playlists and tags. Seeded, so every visitor sees the same week.
- Every track and seeded playlist carries one of 20 covers (`src/demo/covers.ts`): abstract
  SVGs drawn in the browser, five motifs × four palettes, so the demo ships no image files.
  Playlists a visitor creates start without one, as in the app. The track types carry an
  optional `cover_url`, which the production API does not send yet.
- The Library shows invented profiles (`src/demo/profiles.ts`): six hand-written labels and 24
  generated artists, with country, years, styles and collaborators. They carry no links, so a
  made-up name never points at someone's real account.
- `src/demo/db.ts` keeps state for the core loop: assigning tracks in Curate, moving them between
  buckets, finalizing a week into categories, editing categories, playlists and tags, choosing
  styles. A reload starts over.
- `src/demo/handlers.ts` maps routes to the store. Home analytics and Admin coverage are static
  samples (`src/demo/samples.ts`, shared with the README screenshots). Any other API read answers
  404 and any other write 403 "Not available in the demo"; never 401, which would start the
  token-refresh loop.

## Playback

The demo plays real music: eight instrumental tracks made with Suno (three melodic house &
techno, five afro house), normalized to -14 LUFS. The app's own player runs unchanged —
buttons, scrub bar, queue, auto-advance and hotkeys — on top of two stand-ins in
`src/demo/player.ts`:

- `window.Spotify.Player` is a `DemoPlayer` around one `<audio>` element, so
  `PlaybackProvider` loads no Spotify SDK and gets its `ready` and `player_state_changed`
  events from the demo.
- `spotifyWebApi` hands every call to the demo (`src/demo/spotifyBridge.ts`) instead of
  `api.spotify.com`: play by URI, pause, seek, transfer and the device list. It never calls
  Spotify with the demo's fake token.
- Each clip is fetched once and played from a `blob:` URL. Media served through the MSW
  service worker is not seekable in Chrome, so the scrub bar and the seek hotkeys would
  snap back to 0.
- `src/demo/clips.ts` gives each track a clip of its own style, and the seed sets the
  track's length to the clip's, so the time the player shows matches the music.

The mp3s (35 MB) live in the `demo-audio-v1` release, not in git. The Pages build downloads
them into `demo-public/audio/`; for `pnpm dev:demo`, run `pnpm demo:audio` once (needs `gh`).
Without them the player stays paused. New audio means a new release tag (`demo-audio-v2`),
the tag in `pages.yml` and `package.json`, and the files and lengths in `clips.ts`.

## Adding a route

Add it to `demoRoutes` in `src/demo/handlers.ts`, backed by a `DemoDb` method that returns the
SPA's own type. `src/demo/__tests__/openapi.test.ts` fails if a demo route is not in
`docs/api/openapi.yaml`.

## Publishing

`.github/workflows/pages.yml` builds one Pages site on every push to `main` that touches `dbt/`,
`frontend/` or `pages/`: the landing page (`pages/index.html`) at the root, the dbt docs under
`/lineage/` and the demo under `/demo/`. Pages has no SPA fallback, so the site's `404.html` is the
demo's `index.html`: deep links and refreshes under `/demo/` still render.
