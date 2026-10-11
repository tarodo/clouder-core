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
  bundle contains no demo code (checked in the PR: `pnpm build` output has no `msw`).
- `src/demo/seed.ts` builds the catalog: three invented styles, each with a finalized and an open
  triage week, three categories, playlists and tags. Seeded, so every visitor sees the same week.
- `src/demo/db.ts` keeps state for the core loop: assigning tracks in Curate, moving them between
  buckets, finalizing a week into categories, editing categories, playlists and tags, choosing
  styles. A reload starts over.
- `src/demo/handlers.ts` maps routes to the store. Home analytics and Admin coverage are static
  samples (`src/demo/samples.ts`, shared with the README screenshots). Any other API read answers
  404 and any other write 403 "Not available in the demo"; never 401, which would start the
  token-refresh loop.
- Playback is off: the player shows its disconnected state, and `spotifyWebApi` never calls
  Spotify with the demo's fake token.

## Adding a route

Add it to `demoRoutes` in `src/demo/handlers.ts`, backed by a `DemoDb` method that returns the
SPA's own type. `src/demo/__tests__/openapi.test.ts` fails if a demo route is not in
`docs/api/openapi.yaml`.

## Publishing

`.github/workflows/pages.yml` builds one Pages site on every push to `main` that touches `dbt/`,
`frontend/` or `pages/`: the landing page (`pages/index.html`) at the root, the dbt docs under
`/lineage/` and the demo under `/demo/`. Pages has no SPA fallback, so the site's `404.html` is the
demo's `index.html`: deep links and refreshes under `/demo/` still render.
