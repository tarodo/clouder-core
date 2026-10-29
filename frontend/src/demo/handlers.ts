import { http, HttpResponse } from 'msw';
import { DemoDb, DemoError, type LibraryQuery } from './db';
import {
  sampleAutoIngest,
  sampleCoverage,
  sampleSuggestionModels,
  sampleYoutubeReview,
  sampleFunnel,
  sampleListening,
  sampleTimePerTrack,
  sampleWaveform,
} from './samples';

type Method = 'get' | 'post' | 'put' | 'patch' | 'delete';
interface Ctx {
  /** A path parameter; the route pattern guarantees it is present. */
  param: (name: string) => string;
  query: URLSearchParams;
  // The SPA's own request payloads, typed where they are built; the store checks ids.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  body: any;
}
export interface DemoRoute {
  method: Method;
  path: string;
  status?: number;
  resolve: (c: Ctx) => unknown;
}

/** Every API path prefix the SPA calls; anything else (assets, fonts) passes through. */
const API_PREFIXES = [
  '/auth/',
  '/me',
  '/styles',
  '/triage/',
  '/categories',
  '/tracks',
  '/playlists',
  '/tags',
  '/labels',
  '/artists',
  '/admin/',
  '/runs/',
  '/v1/',
];
const NOT_IN_DEMO = 'Not available in the demo — it runs on sample data in your browser.';

function libraryQuery(q: URLSearchParams): LibraryQuery {
  return {
    style: q.get('style') ?? undefined,
    q: q.get('q') ?? undefined,
    sort: q.get('sort') === 'recent' ? 'recent' : 'name',
    my: (q.get('my') as LibraryQuery['my']) ?? undefined,
    page: Number(q.get('page') ?? 1),
    limit: Number(q.get('limit') ?? 50),
  };
}

function page<T>(items: T[], q: URLSearchParams) {
  const limit = Number(q.get('limit') ?? 50);
  const offset = Number(q.get('offset') ?? 0);
  return { items: items.slice(offset, offset + limit), total: items.length, limit, offset };
}

export function demoRoutes(db: DemoDb, origin: string): DemoRoute[] {
  void origin;
  const me = {
    id: 'u-demo',
    spotify_id: 'demo',
    display_name: 'Demo DJ',
    is_admin: true,
    ytmusic_connected: false,
    sessions: [],
  };
  return [
    {
      method: 'post',
      path: '/auth/refresh',
      resolve: () => ({ access_token: 'demo', spotify_access_token: 'demo', expires_in: 3600 }),
    },
    { method: 'post', path: '/auth/logout', status: 204, resolve: () => undefined },
    { method: 'get', path: '/me', resolve: () => me },
    {
      method: 'get',
      path: '/styles',
      resolve: ({ query }) =>
        page(query.get('scope') === 'all' ? db.styles('all') : db.styles('mine'), query),
    },
    {
      method: 'put',
      path: '/me/styles',
      status: 204,
      resolve: ({ body }) => db.setMyStyles(body.style_ids),
    },
    {
      method: 'get',
      path: '/styles/:styleId/triage/blocks',
      resolve: ({ param, query }) =>
        page(
          db.blocksByStyle(param('styleId'), (query.get('status') as never) ?? undefined),
          query,
        ),
    },
    { method: 'get', path: '/triage/blocks/:id', resolve: ({ param }) => db.block(param('id')) },
    {
      method: 'get',
      path: '/triage/blocks/:id/buckets/:bucketId/tracks',
      resolve: ({ param, query }) =>
        page(
          db.bucketTracks(param('id'), param('bucketId'), query.get('search') ?? undefined),
          query,
        ),
    },
    {
      method: 'post',
      path: '/triage/blocks/:id/move',
      resolve: ({ param, body }) => ({
        moved: db.move(param('id'), body.from_bucket_id, body.to_bucket_id, body.track_ids),
      }),
    },
    {
      method: 'post',
      path: '/triage/blocks/:id/finalize',
      resolve: ({ param }) => db.finalize(param('id')),
    },
    {
      method: 'get',
      path: '/styles/:styleId/categories',
      resolve: ({ param, query }) => page(db.categoriesByStyle(param('styleId')), query),
    },
    {
      method: 'post',
      path: '/styles/:styleId/categories',
      status: 201,
      resolve: ({ param, body }) => db.createCategory(param('styleId'), body.name),
    },
    {
      method: 'put',
      path: '/styles/:styleId/categories/order',
      resolve: ({ param, body }) => ({
        items: db.reorderCategories(param('styleId'), body.category_ids),
      }),
    },
    { method: 'get', path: '/categories/:id', resolve: ({ param }) => db.category(param('id')) },
    {
      method: 'patch',
      path: '/categories/:id',
      resolve: ({ param, body }) => db.renameCategory(param('id'), body.name),
    },
    {
      method: 'delete',
      path: '/categories/:id',
      status: 204,
      resolve: ({ param }) => db.deleteCategory(param('id')),
    },
    {
      method: 'get',
      path: '/categories/:id/tracks',
      resolve: ({ param, query }) =>
        page(
          db.categoryTracks(param('id'), {
            search: query.get('search') ?? undefined,
            sort: (query.get('sort') as never) ?? undefined,
            order: (query.get('order') as never) ?? undefined,
            tags: query.get('tags')?.split(',').filter(Boolean),
            match: (query.get('match') as never) ?? undefined,
            fresh: query.get('fresh') === '1' || query.get('fresh') === 'true',
          }),
          query,
        ),
    },
    {
      method: 'post',
      path: '/categories/:id/tracks',
      status: 201,
      resolve: ({ param, body }) =>
        db.addToCategory(param('id'), body.track_id, {
          added_at: body.added_at,
          source_triage_block_id: body.source_triage_block_id,
        }),
    },
    {
      method: 'delete',
      path: '/categories/:id/tracks/:trackId',
      status: 204,
      resolve: ({ param }) => db.removeFromCategory(param('id'), param('trackId')),
    },
    {
      method: 'get',
      path: '/playlists',
      resolve: ({ query }) =>
        page(
          db.playlists({
            status: (query.get('status') as never) ?? undefined,
            search: query.get('search') ?? undefined,
          }),
          query,
        ),
    },
    {
      method: 'post',
      path: '/playlists',
      status: 201,
      resolve: ({ body }) => db.createPlaylist(body),
    },
    { method: 'get', path: '/playlists/:id', resolve: ({ param }) => db.playlist(param('id')) },
    {
      method: 'patch',
      path: '/playlists/:id',
      resolve: ({ param, body }) => db.patchPlaylist(param('id'), body),
    },
    {
      method: 'delete',
      path: '/playlists/:id',
      status: 204,
      resolve: ({ param }) => db.deletePlaylist(param('id')),
    },
    {
      method: 'get',
      path: '/playlists/:id/tracks',
      resolve: ({ param, query }) => page(db.playlistTracks(param('id')), query),
    },
    {
      method: 'post',
      path: '/playlists/:id/tracks',
      status: 201,
      resolve: ({ param, body }) => db.addToPlaylist(param('id'), body.track_ids),
    },
    {
      method: 'delete',
      path: '/playlists/:id/tracks/:trackId',
      status: 204,
      resolve: ({ param }) => db.removeFromPlaylist(param('id'), param('trackId')),
    },
    {
      method: 'post',
      path: '/playlists/:id/tracks/order',
      resolve: ({ param, body }) => (
        db.reorderPlaylist(param('id'), body.track_ids),
        { correlation_id: 'demo' }
      ),
    },
    { method: 'get', path: '/tags', resolve: ({ query }) => page(db.tags(), query) },
    {
      method: 'post',
      path: '/tags',
      status: 201,
      resolve: ({ body }) => db.createTag(body.name, body.color ?? null),
    },
    {
      method: 'patch',
      path: '/tags/:tagId',
      resolve: ({ param, body }) => db.patchTag(param('tagId'), body),
    },
    {
      method: 'delete',
      path: '/tags/:tagId',
      status: 204,
      resolve: ({ param }) => db.deleteTag(param('tagId')),
    },
    {
      method: 'get',
      path: '/tracks/:trackId/tags',
      resolve: ({ param }) => ({ tags: db.trackTags(param('trackId')) }),
    },
    {
      method: 'post',
      path: '/tracks/:trackId/tags',
      resolve: ({ param, body }) => ({ tags: db.tagTrack(param('trackId'), body.tag_id) }),
    },
    {
      method: 'delete',
      path: '/tracks/:trackId/tags/:tagId',
      status: 204,
      resolve: ({ param }) => db.untagTrack(param('trackId'), param('tagId')),
    },
    {
      method: 'get',
      path: '/tracks/:trackId/waveform',
      resolve: ({ param }) => sampleWaveform(param('trackId')),
    },
    {
      method: 'get',
      path: '/tracks/:trackId/comments',
      resolve: () => ({ status: 'empty', comment_count: 0, video_url: null, comments: [] }),
    },
    { method: 'get', path: '/v1/analytics/listening', resolve: () => sampleListening() },
    { method: 'get', path: '/v1/analytics/funnel', resolve: () => sampleFunnel() },
    {
      method: 'get',
      path: '/v1/analytics/time-per-track',
      resolve: ({ query }) => sampleTimePerTrack(Number(query.get('days') ?? 30)),
    },
    {
      method: 'get',
      path: '/admin/coverage',
      resolve: ({ query }) => sampleCoverage(Number(query.get('week_year') ?? 2026)),
    },
    { method: 'get', path: '/admin/runs', resolve: () => ({ items: [] }) },
    {
      method: 'get',
      path: '/admin/youtube/review',
      resolve: ({ query }) =>
        sampleYoutubeReview(
          Number(query.get('style_id')),
          Number(query.get('week_year')),
          Number(query.get('week_number')),
        ),
    },
    {
      method: 'post',
      path: '/admin/youtube/review/:track_id',
      resolve: ({ param, body }) => ({ track_id: param('track_id'), action: body.action }),
    },
    { method: 'get', path: '/admin/auto-ingest', resolve: () => sampleAutoIngest() },
    {
      method: 'get',
      path: '/admin/analysis/status',
      resolve: () => ({
        last_claim_at: new Date(Date.now() - 2 * 60_000).toISOString(),
        last_result_at: new Date(Date.now() - 4 * 60_000).toISOString(),
        analyzers: [
          { name: 'ai_deezer', due: 46, leased: 0, ok: 3354, ai_detected: 96, failed: 12, unusable_source: 3, last_result_at: new Date(Date.now() - 4 * 60_000).toISOString() },
          { name: 'ai_lofcz', due: 46, leased: 0, ok: 3354, ai_detected: 58, failed: 12, unusable_source: 3, last_result_at: new Date(Date.now() - 4 * 60_000).toISOString() },
          { name: 'light_profile', due: 1260, leased: 20, ok: 2135, ai_detected: 0, failed: 4, unusable_source: 1, last_result_at: new Date(Date.now() - 9 * 60_000).toISOString() },
        ],
        pair: { high: 41, medium: 17, low: 55, clean: 3241 },
        queue: { total: 3400, waiting: 30, in_progress: 1, failed: 12, unusable: 3 },
        profile: { total: 3400, waiting: 1240, in_progress: 20, profiled: 2135, failed: 4, unusable: 1 },
        models: {
          count: 3,
          last_trained_at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
          items: sampleSuggestionModels(),
        },
      }),
    },
    {
      method: 'get',
      path: '/admin/youtube/search-status',
      resolve: () => ({
        status: 'idle',
        paused_until: null,
        queue: { waiting_messages: 0, in_flight: 0, delayed: 0 },
        tracks: { total: 4600, waiting: 255, searched_last_10_min: 0 },
        results: { matched: 3400, needs_review: 940, not_found: 3, error: 2, videos: 1200 },
      }),
    },
    {
      method: 'get',
      path: '/admin/spotify/search-status',
      resolve: () => ({
        status: 'idle',
        paused_until: null,
        queue: { waiting_messages: 0, in_flight: 0, delayed: 0 },
        tracks: {
          total: 4600,
          found: 4410,
          not_found: 180,
          waiting: 0,
          no_isrc: 10,
          searched_last_10_min: 0,
        },
      }),
    },
    {
      method: 'get',
      path: '/admin/users',
      resolve: () => ({ users: [{ id: me.id, display_name: me.display_name }] }),
    },
    { method: 'get', path: '/labels', resolve: ({ query }) => db.labels(libraryQuery(query)) },
    {
      method: 'get',
      path: '/labels/:labelId',
      resolve: ({ param }) => db.labelDetail(param('labelId')),
    },
    {
      method: 'put',
      path: '/labels/:labelId/preference',
      status: 204,
      resolve: ({ param, body }) => db.setLabelPreference(param('labelId'), body.status),
    },
    { method: 'get', path: '/artists', resolve: ({ query }) => db.artists(libraryQuery(query)) },
    {
      method: 'get',
      path: '/artists/:artistId',
      resolve: ({ param }) => db.artistDetail(param('artistId')),
    },
    {
      method: 'put',
      path: '/artists/:artistId/preference',
      status: 204,
      resolve: ({ param, body }) => db.setArtistPreference(param('artistId'), body.status),
    },
  ];
}

export function demoHandlers(
  db = new DemoDb(),
  origin = globalThis.location?.origin ?? 'http://localhost',
) {
  const routes = demoRoutes(db, origin).map((r) =>
    http[r.method](`${origin}${r.path}`, async ({ request, params }) => {
      const body =
        r.method === 'get' || r.method === 'delete'
          ? undefined
          : await request.json().catch(() => ({}));
      try {
        const out = r.resolve({
          param: (name: string) => {
            const value = (params as Record<string, string | undefined>)[name];
            if (value === undefined) throw new DemoError(400, 'bad_request', `Missing ${name}.`);
            return value;
          },
          query: new URL(request.url).searchParams,
          body,
        });
        if (r.status === 204) return new HttpResponse(null, { status: 204 });
        return HttpResponse.json(out as Record<string, unknown>, { status: r.status ?? 200 });
      } catch (e) {
        if (e instanceof DemoError)
          return HttpResponse.json(
            { error_code: e.code, message: e.message },
            { status: e.status },
          );
        throw e;
      }
    }),
  );
  // Everything else under the API: reads are "not found" (the SPA does not retry them),
  // writes are refused with a message. Never 401 — it would start the refresh loop.
  const fallback = http.all(`${origin}/*`, ({ request }) => {
    const { pathname } = new URL(request.url);
    if (!API_PREFIXES.some((p) => pathname.startsWith(p))) return undefined;
    return request.method === 'GET'
      ? HttpResponse.json(
          { error_code: 'not_found', message: 'Not in the demo data.' },
          { status: 404 },
        )
      : HttpResponse.json({ error_code: 'forbidden', message: NOT_IN_DEMO }, { status: 403 });
  });
  return [...routes, fallback];
}
