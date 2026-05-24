import { http, HttpResponse } from 'msw';

const PLAYLIST_DEFAULTS = [
  http.get('http://localhost/playlists', () =>
    HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 }),
  ),
  http.post('http://localhost/playlists', () =>
    HttpResponse.json(
      { error_code: 'unhandled', message: 'override in test' },
      { status: 500 },
    ),
  ),
  http.get('http://localhost/playlists/:id', () =>
    HttpResponse.json(
      { error_code: 'playlist_not_found', message: 'not found' },
      { status: 404 },
    ),
  ),
  http.patch('http://localhost/playlists/:id', () =>
    HttpResponse.json(
      { error_code: 'unhandled', message: 'override in test' },
      { status: 500 },
    ),
  ),
  http.delete('http://localhost/playlists/:id', () => new HttpResponse(null, { status: 204 })),
  http.get('http://localhost/playlists/:id/tracks', () =>
    HttpResponse.json({ items: [], total: 0, limit: 100, offset: 0 }),
  ),
  http.post('http://localhost/playlists/:id/tracks', () =>
    HttpResponse.json(
      { added: [], skipped_duplicates: [], position_after: 0 },
      { status: 201 },
    ),
  ),
  http.delete('http://localhost/playlists/:id/tracks/:track_id', () =>
    new HttpResponse(null, { status: 204 }),
  ),
  http.post('http://localhost/playlists/:id/tracks/order', () =>
    HttpResponse.json({ correlation_id: 'test' }),
  ),
  http.post('http://localhost/playlists/:id/cover/upload-url', () =>
    HttpResponse.json(
      { error_code: 'unhandled', message: 'override in test' },
      { status: 500 },
    ),
  ),
  http.post('http://localhost/playlists/:id/cover/confirm', () =>
    HttpResponse.json(
      { error_code: 'unhandled', message: 'override in test' },
      { status: 500 },
    ),
  ),
  http.delete('http://localhost/playlists/:id/cover', () => new HttpResponse(null, { status: 200 })),
  http.post('http://localhost/playlists/:id/tracks/import-spotify', () =>
    HttpResponse.json({ added: [], skipped: [], position_after: 0 }, { status: 201 }),
  ),
  http.post('http://localhost/playlists/:id/publish', () =>
    HttpResponse.json(
      { error_code: 'unhandled', message: 'override in test' },
      { status: 500 },
    ),
  ),
];

export const handlers = [
  http.get('http://localhost/me', () =>
    HttpResponse.json({ id: 'u1', spotify_id: 'sp1', display_name: 'Roman', is_admin: false }),
  ),
  http.get('http://localhost/tags', () =>
    HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
  ),
  http.get('http://localhost/admin/coverage', ({ request }) => {
    const url = new URL(request.url);
    const year = Number(url.searchParams.get('week_year') ?? '0');
    return HttpResponse.json({
      week_year: year,
      weeks_in_year: 52,
      styles: [],
      correlation_id: 'test',
    });
  }),
  http.get('http://localhost/admin/runs', () =>
    HttpResponse.json({ items: [] }),
  ),
  http.post('http://localhost/admin/beatport/ingest', async () =>
    HttpResponse.json({
      run_id: 'test-run',
      run_status: 'RAW_SAVED',
      processing_status: 'QUEUED',
      is_custom_range: false,
    }),
  ),
  ...PLAYLIST_DEFAULTS,
];
