import { beforeEach, describe, expect, it } from 'vitest';
import { server } from '../../test/setup';
import { demoHandlers } from '../handlers';

const get = (p: string) => fetch(`http://localhost${p}`);
const send = (method: string, p: string, body?: unknown) =>
  fetch(`http://localhost${p}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

beforeEach(() => server.use(...demoHandlers()));

describe('demo handlers', () => {
  it('signs the visitor in as an admin without a 401', async () => {
    const refresh = await (await send('POST', '/auth/refresh')).json();
    expect(refresh.expires_in).toBe(3600);
    const me = await (await get('/me')).json();
    expect(me.is_admin).toBe(true);
  });

  it('serves the core loop with state', async () => {
    const styles = await (await get('/styles?limit=200&offset=0')).json();
    const styleId = styles.items[0].id;
    const blocks = await (
      await get(`/styles/${styleId}/triage/blocks?status=IN_PROGRESS&limit=50&offset=0`)
    ).json();
    const block = await (await get(`/triage/blocks/${blocks.items[0].id}`)).json();
    const fresh = block.buckets.find((b: { bucket_type: string }) => b.bucket_type === 'NEW');
    const fav = block.buckets.find((b: { bucket_type: string }) => b.bucket_type === 'FAV');
    const tracks = await (
      await get(`/triage/blocks/${block.id}/buckets/${fresh.id}/tracks?limit=50&offset=0`)
    ).json();
    const moved = await send('POST', `/triage/blocks/${block.id}/move`, {
      from_bucket_id: fresh.id,
      to_bucket_id: fav.id,
      track_ids: [tracks.items[0].track_id],
    });
    expect((await moved.json()).moved).toBe(1);
    const favTracks = await (
      await get(`/triage/blocks/${block.id}/buckets/${fav.id}/tracks?limit=50&offset=0`)
    ).json();
    expect(favTracks.items.map((t: { track_id: string }) => t.track_id)).toContain(
      tracks.items[0].track_id,
    );
  });

  it('serves the library: lists, profiles and likes', async () => {
    const list = await (
      await get('/labels?style=melodic-house-and-techno&sort=name&page=1&limit=24')
    ).json();
    expect(list.items.length).toBeGreaterThan(0);
    const label = list.items[0];
    const detail = await (await get(`/labels/${label.id}`)).json();
    expect(detail.label_name).toBe(label.name);
    const liked = await send('PUT', `/labels/${label.id}/preference`, { status: 'liked' });
    expect(liked.status).toBe(204);
    expect((await (await get(`/labels/${label.id}`)).json()).my_preference).toBe('liked');
    const artists = await (await get('/artists?style=afro-house&sort=name&page=1&limit=24')).json();
    const artist = await (await get(`/artists/${artists.items[0].id}`)).json();
    expect(artist.artist_name).toBe(artists.items[0].name);
  });

  it('serves track tags in the production shape', async () => {
    const styles = await (await get('/styles?limit=200&offset=0')).json();
    const blocks = await (
      await get(`/styles/${styles.items[0].id}/triage/blocks?limit=50&offset=0`)
    ).json();
    const block = await (await get(`/triage/blocks/${blocks.items[0].id}`)).json();
    const fresh = block.buckets.find((b: { bucket_type: string }) => b.bucket_type === 'NEW');
    const tracks = await (
      await get(`/triage/blocks/${block.id}/buckets/${fresh.id}/tracks?limit=50&offset=0`)
    ).json();
    const trackId = tracks.items[0].track_id;
    const tag = await (await send('POST', '/tags', { name: 'demo-shape', color: null })).json();
    const added = await (await send('POST', `/tracks/${trackId}/tags`, { tag_id: tag.id })).json();
    expect(added.tags.map((t: { id: string }) => t.id)).toContain(tag.id);
    const listed = await (await get(`/tracks/${trackId}/tags`)).json();
    expect(listed.tags.map((t: { id: string }) => t.id)).toContain(tag.id);
  });

  it('answers unknown reads with 404 and unknown writes with 403', async () => {
    const read = await get('/admin/labels/backlog?limit=100');
    expect(read.status).toBe(404);
    expect((await read.json()).error_code).toBe('not_found');
    const write = await send('POST', '/playlists/p1/publish', { confirm_overwrite: false });
    expect(write.status).toBe(403);
    expect((await write.json()).message).toMatch(/demo/i);
  });

  it('maps store errors to API errors', async () => {
    const res = await get('/triage/blocks/nope');
    expect(res.status).toBe(404);
  });
});
