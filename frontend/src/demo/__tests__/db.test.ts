import { describe, expect, it } from 'vitest';
import { CLIPS } from '../clips';
import { DemoDb, DemoError } from '../db';

const CLIP_MS = Object.fromEntries(
  Object.values(CLIPS)
    .flat()
    .map((c) => [c.file, c.ms]),
);

function first<T>(xs: readonly T[]): T {
  const [x] = xs;
  if (x === undefined) throw new Error('empty');
  return x;
}

const firstOpenBlock = (db: DemoDb) => first(db.blocksByStyle('s-melodic', 'IN_PROGRESS'));

describe('DemoDb', () => {
  it('serves two selected styles with an open week each', () => {
    const db = new DemoDb();
    expect(db.styles('mine').map((s) => s.name)).toEqual(['Melodic House & Techno', 'Afro House']);
    expect(db.styles('all').length).toBeGreaterThan(3);
    for (const s of db.styles('mine'))
      expect(db.blocksByStyle(s.id, 'IN_PROGRESS')).toHaveLength(1);
  });

  it('moves a track between buckets and keeps the counts', () => {
    const db = new DemoDb();
    const block = db.block(firstOpenBlock(db).id);
    const from = block.buckets.find((b) => b.bucket_type === 'NEW')!;
    const to = block.buckets.find((b) => b.bucket_type === 'STAGING')!;
    const track = first(db.bucketTracks(block.id, from.id));
    expect(db.move(block.id, from.id, to.id, [track.track_id])).toBe(1);
    const after = db.block(block.id);
    expect(after.buckets.find((b) => b.id === from.id)!.track_count).toBe(from.track_count - 1);
    expect(after.buckets.find((b) => b.id === to.id)!.track_count).toBe(to.track_count + 1);
    expect(db.bucketTracks(block.id, to.id).map((t) => t.track_id)).toContain(track.track_id);
    expect(db.move(block.id, from.id, to.id, [track.track_id])).toBe(0);
  });

  it('finalize promotes staging tracks into their categories', () => {
    const db = new DemoDb();
    const block = db.block(firstOpenBlock(db).id);
    const staging = block.buckets.find((b) => b.bucket_type === 'STAGING' && b.track_count > 0)!;
    const before = db.category(staging.category_id!).track_count;
    const res = db.finalize(block.id);
    expect(res.block.status).toBe('FINALIZED');
    expect(res.promoted[staging.category_id!]).toBe(staging.track_count);
    expect(db.category(staging.category_id!).track_count).toBe(before + staging.track_count);
    expect(() => db.finalize(block.id)).toThrow(DemoError);
  });

  it('adds category tracks to a playlist once and reorders them', () => {
    const db = new DemoDb();
    const playlist = first(db.playlists({}));
    const cat = first(db.categoriesByStyle('s-melodic'));
    const ids = db
      .categoryTracks(cat.id, {})
      .slice(0, 2)
      .map((t) => t.id);
    db.addToPlaylist(playlist.id, ids);
    const again = db.addToPlaylist(playlist.id, ids);
    expect(again.added).toEqual([]);
    expect([...again.skipped_duplicates].sort()).toEqual([...ids].sort());
    const order = db
      .playlistTracks(playlist.id)
      .map((t) => t.track_id)
      .reverse();
    db.reorderPlaylist(playlist.id, order);
    expect(db.playlistTracks(playlist.id).map((t) => t.track_id)).toEqual(order);
    expect(db.categoryTracks(cat.id, {}).find((t) => t.id === first(ids))!.used_in_playlist).toBe(
      true,
    );
  });

  it('tags a track and filters a category by tag', () => {
    const db = new DemoDb();
    const tag = first(db.tags());
    const cat = first(db.categoriesByStyle('s-afro'));
    const track = first(db.categoryTracks(cat.id, {}));
    db.tagTrack(track.id, tag.id);
    expect(db.categoryTracks(cat.id, { tags: [tag.id] }).map((t) => t.id)).toContain(track.id);
  });

  it('remembers the selected styles', () => {
    const db = new DemoDb();
    db.setMyStyles(['s-afro']);
    expect(db.styles('mine').map((s) => s.id)).toEqual(['s-afro']);
  });

  it('is the same catalog for every visitor', () => {
    const a = new DemoDb();
    const b = new DemoDb();
    expect(a.block(firstOpenBlock(a).id)).toEqual(b.block(firstOpenBlock(b).id));
  });

  it('fresh hides tracks already in a playlist', () => {
    const db = new DemoDb();
    const cat = first(db.categoriesByStyle('s-melodic'));
    const all = db.categoryTracks(cat.id, {});
    expect(all.some((t) => t.used_in_playlist)).toBe(true);
    const fresh = db.categoryTracks(cat.id, { fresh: true });
    expect(fresh.length).toBeGreaterThan(0);
    expect(fresh.every((t) => !t.used_in_playlist)).toBe(true);
  });

  it('names weeks by Saturday-week number (ADR-0003: Oct 3 2026 starts week 40)', () => {
    const db = new DemoDb();
    expect(firstOpenBlock(db).name).toMatch(/^Week 40 · Oct 3/);
    expect(first(db.blocksByStyle('s-melodic', 'FINALIZED')).name).toMatch(/^Week 39 · Sep 26/);
  });

  it('gives some releases a cover, drawn from at most 20 designs', () => {
    const db = new DemoDb();
    const block = db.block(firstOpenBlock(db).id);
    const tracks = block.buckets.flatMap((b) => db.bucketTracks(block.id, b.id));
    const covers = tracks.map((t) => t.cover_url ?? null);
    expect(covers.some((c) => c === null)).toBe(true);
    const drawn = covers.filter((c): c is string => c !== null);
    expect(drawn.length).toBeGreaterThan(tracks.length / 3);
    expect(drawn.every((c) => c.startsWith('data:image/svg+xml'))).toBe(true);
    const all = new Set(
      db
        .styles('mine')
        .flatMap((st) =>
          db
            .blocksByStyle(st.id)
            .flatMap((b) =>
              db
                .block(b.id)
                .buckets.flatMap((bk) => db.bucketTracks(b.id, bk.id).map((t) => t.cover_url)),
            ),
        ),
    );
    all.delete(null);
    all.delete(undefined);
    expect(all.size).toBeGreaterThan(10);
    expect(all.size).toBeLessThanOrEqual(20);
  });

  it('shows artwork on the first track a visitor curates in each style', () => {
    const db = new DemoDb();
    for (const st of db.styles('mine')) {
      const block = db.block(first(db.blocksByStyle(st.id, 'IN_PROGRESS')).id);
      const fresh = block.buckets.find((b) => b.bucket_type === 'NEW')!;
      expect(first(db.bucketTracks(block.id, fresh.id)).cover_url, st.name).toBeTruthy();
    }
  });

  it('describes the label and artists of every track', () => {
    const db = new DemoDb();
    const block = db.block(firstOpenBlock(db).id);
    for (const t of block.buckets.flatMap((b) => db.bucketTracks(block.id, b.id))) {
      const label = db.labelDetail(t.label_id!);
      expect(label.label_name).toBe(t.label_name);
      expect(String(label.tagline)).not.toBe('');
      expect(String(label.country)).toMatch(/^[A-Z]{2}$/);
      for (const a of t.artists) {
        const artist = db.artistDetail(a.id);
        expect(artist.artist_name).toBe(a.name);
        expect(String(artist.summary)).not.toBe('');
      }
    }
  });

  it('lists the labels of a style and keeps a like', () => {
    const db = new DemoDb();
    const page = db.labels({ style: 's-melodic' });
    expect(page.items.length).toBeGreaterThan(0);
    expect(page.items.every((l) => l.style === 'Melodic House & Techno' && l.track_count > 0)).toBe(
      true,
    );
    const label = first(page.items);
    db.setLabelPreference(label.id, 'liked');
    expect(db.labelDetail(label.id).my_preference).toBe('liked');
    expect(db.labels({ style: 's-melodic', my: 'liked' }).items.map((l) => l.id)).toEqual([
      label.id,
    ]);
    expect(first(db.artists({ style: 's-afro' }).items).style).toBe('Afro House');
    // The Library route carries the style as a slug of its name.
    expect(db.labels({ style: 'melodic-house-and-techno' }).items.map((l) => l.id)).toEqual(
      page.items.map((l) => l.id),
    );
  });

  it("has the Library's default style, so /library opens on real rows", () => {
    expect(new DemoDb().labels({ style: 'melodic-house-and-techno' }).items.length).toBeGreaterThan(
      0,
    );
  });

  it('gives every track a preview clip of its own style, using every clip', () => {
    const db = new DemoDb();
    const used = new Set<string>();
    for (const st of db.styles('mine')) {
      const prefix = st.id === 's-afro' ? 'afro' : 'melodic';
      for (const b of db.blocksByStyle(st.id)) {
        for (const bucket of db.block(b.id).buckets) {
          for (const t of db.bucketTracks(b.id, bucket.id)) {
            const clip = db.clipFor(t.spotify_id!);
            expect(clip).toMatch(new RegExp(`^${prefix}-\\d\\.mp3$`));
            // The bar, the seek keys and the Length label all agree with what plays.
            expect(t.length_ms).toBe(CLIP_MS[clip!]);
            used.add(clip!);
          }
        }
      }
    }
    expect(used.size).toBe(8);
    expect(db.clipFor('unknown')).toBeNull();
  });

  it('returns no tracks for an unknown bucket and 404s an unknown block', () => {
    const db = new DemoDb();
    expect(db.bucketTracks(firstOpenBlock(db).id, 'missing')).toEqual([]);
    expect(() => db.block('missing')).toThrow(DemoError);
  });
});
