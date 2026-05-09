import { http, HttpResponse } from 'msw';

export const handlers = [
  http.get('http://localhost/me', () =>
    HttpResponse.json({ id: 'u1', spotify_id: 'sp1', display_name: 'Roman', is_admin: false }),
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
];
