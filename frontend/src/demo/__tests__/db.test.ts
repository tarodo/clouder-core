import { describe, expect, it } from 'vitest';
import { DemoDb, DemoError } from '../db';

function first<T>(xs: readonly T[]): T {
  const [x] = xs;
  if (x === undefined) throw new Error('empty');
  return x;
}

const firstOpenBlock = (db: DemoDb) => first(db.blocksByStyle('s-tech', 'IN_PROGRESS'));

describe('DemoDb', () => {
  it('serves three selected styles with an open week each', () => {
    const db = new DemoDb();
    expect(db.styles('mine').map((s) => s.name)).toEqual([
      'Tech House',
      'Melodic House & Techno',
      'Afro House',
    ]);
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
    const cat = first(db.categoriesByStyle('s-tech'));
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
    const cat = first(db.categoriesByStyle('s-tech'));
    const all = db.categoryTracks(cat.id, {});
    expect(all.some((t) => t.used_in_playlist)).toBe(true);
    const fresh = db.categoryTracks(cat.id, { fresh: true });
    expect(fresh.length).toBeGreaterThan(0);
    expect(fresh.every((t) => !t.used_in_playlist)).toBe(true);
  });

  it('names weeks by Saturday-week number (ADR-0003: Oct 3 2026 starts week 40)', () => {
    const db = new DemoDb();
    expect(firstOpenBlock(db).name).toMatch(/^Week 40 · Oct 3/);
    expect(first(db.blocksByStyle('s-tech', 'FINALIZED')).name).toMatch(/^Week 39 · Sep 26/);
  });

  it('returns no tracks for an unknown bucket and 404s an unknown block', () => {
    const db = new DemoDb();
    expect(db.bucketTracks(firstOpenBlock(db).id, 'missing')).toEqual([]);
    expect(() => db.block('missing')).toThrow(DemoError);
  });
});
