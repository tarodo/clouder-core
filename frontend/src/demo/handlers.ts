import { http, HttpResponse } from 'msw';
import { DemoDb, DemoError } from './db';
import {
  sampleAutoIngest,
  sampleCoverage,
  sampleFunnel,
  sampleListening,
  sampleTimePerTrack,
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
          }),
          query,
        ),
    },
    {
      method: 'post',
      path: '/categories/:id/tracks',
      status: 201,
      resolve: ({ param, body }) => db.addToCategory(param('id'), body.track_id),
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
      resolve: ({ param }) => ({ items: db.trackTags(param('trackId')) }),
    },
    {
      method: 'post',
      path: '/tracks/:trackId/tags',
      resolve: ({ param, body }) => ({ items: db.tagTrack(param('trackId'), body.tag_id) }),
    },
    {
      method: 'delete',
      path: '/tracks/:trackId/tags/:tagId',
      status: 204,
      resolve: ({ param }) => db.untagTrack(param('trackId'), param('tagId')),
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
    { method: 'get', path: '/admin/auto-ingest', resolve: () => sampleAutoIngest() },
    {
      method: 'get',
      path: '/admin/users',
      resolve: () => ({ users: [{ id: me.id, display_name: me.display_name }] }),
    },
    {
      method: 'get',
      path: '/labels',
      resolve: ({ query }) => ({
        items: [],
        total: 0,
        page: 1,
        limit: Number(query.get('limit') ?? 50),
      }),
    },
    {
      method: 'get',
      path: '/artists',
      resolve: ({ query }) => ({
        items: [],
        total: 0,
        page: 1,
        limit: Number(query.get('limit') ?? 50),
      }),
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
