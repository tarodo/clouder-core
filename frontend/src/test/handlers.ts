import { http, HttpResponse } from 'msw';

export const handlers = [
  http.get('http://localhost/me', () =>
    HttpResponse.json({ id: 'u1', spotify_id: 'sp1', display_name: 'Roman', is_admin: false }),
  ),
];
