/**
 * In-memory store behind the demo's API. It keeps real state for the core loop —
 * curate, triage, finalize, categories, playlists, tags, style selection — and answers
 * in the SPA's own response types. State lives for the page; a reload starts over.
 */
import type { Style } from '../hooks/useStyles';
import type { CatalogStyle } from '../hooks/useAllStyles';
import type {
  TriageBlockSummary,
  TriageStatus,
} from '../features/triage/hooks/useTriageBlocksByStyle';
import type { TriageBlock } from '../features/triage/hooks/useTriageBlock';
import type { BucketTrack } from '../features/triage/hooks/useBucketTracks';
import type { FinalizeResponse } from '../features/triage/hooks/useFinalizeTriageBlock';
import type { Category } from '../features/categories/hooks/useCategoriesByStyle';
import type { CategoryTrack } from '../features/categories/hooks/useCategoryTracks';
import type {
  AddTracksResult,
  Playlist,
  PlaylistStatus,
  PlaylistTrack,
} from '../features/playlists/lib/playlistTypes';
import type { Tag } from '../features/tags/hooks/useTags';
import {
  buildSeed,
  type DemoBlock,
  type DemoBucket,
  type DemoCategory,
  type DemoPlaylist,
  type DemoSeed,
  type DemoTrack,
} from './seed';

export class DemoError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export interface CategoryTrackQuery {
  search?: string;
  sort?: 'title' | 'spotify_release_date' | 'added_at';
  order?: 'asc' | 'desc';
  tags?: string[];
  match?: 'any' | 'all';
  /** Only tracks not yet in any playlist (the category page's "Fresh only"). */
  fresh?: boolean;
}

const NOW = () => new Date().toISOString();
let counter = 0;
const newId = (prefix: string) => `${prefix}-new-${++counter}`;

function found<T>(value: T | undefined, entity: string): T {
  if (value === undefined)
    throw new DemoError(404, `${entity}_not_found`, `No such ${entity} in the demo.`);
  return value;
}

const matches = (t: DemoTrack, search?: string) =>
  !search ||
  `${t.title} ${t.mix_name} ${t.artists.map((a) => a.name).join(' ')} ${t.label.name}`
    .toLowerCase()
    .includes(search.toLowerCase());

export class DemoDb {
  private readonly s: DemoSeed;
  private readonly tracks: Map<string, DemoTrack>;

  constructor(seed: DemoSeed = buildSeed()) {
    this.s = seed; // buildSeed() returns a fresh object per store
    this.tracks = new Map(this.s.tracks.map((t) => [t.id, t]));
  }

  // ── styles ────────────────────────────────────────────────────────────────

  styles(scope: 'mine'): Style[];
  styles(scope: 'all'): CatalogStyle[];
  styles(scope: 'mine' | 'all'): Style[] | CatalogStyle[] {
    if (scope === 'mine') {
      return this.s.selected.map((id) =>
        found(
          this.s.styles.find((st) => st.id === id),
          'style',
        ),
      );
    }
    return this.s.styles.map((st) => {
      const position = this.s.selected.indexOf(st.id);
      return { ...st, selected: position >= 0, position: position >= 0 ? position : null };
    });
  }

  setMyStyles(ids: string[]): void {
    this.s.selected = ids.filter((id) => this.s.styles.some((st) => st.id === id));
  }

  private styleName(id: string): string {
    return found(
      this.s.styles.find((st) => st.id === id),
      'style',
    ).name;
  }

  // ── triage ────────────────────────────────────────────────────────────────

  private rawBlock(id: string): DemoBlock {
    return found(
      this.s.blocks.find((b) => b.id === id),
      'block',
    );
  }

  private rawBucket(block: DemoBlock, id: string): DemoBucket {
    return found(
      block.buckets.find((b) => b.id === id),
      'bucket',
    );
  }

  private summary(b: DemoBlock): TriageBlockSummary {
    const { buckets, ...rest } = b;
    return {
      ...rest,
      style_name: this.styleName(b.style_id),
      track_count: buckets.reduce((n, bucket) => n + bucket.tracks.length, 0),
    };
  }

  blocksByStyle(styleId: string, status?: TriageStatus): TriageBlockSummary[] {
    return this.s.blocks
      .filter((b) => b.style_id === styleId && (!status || b.status === status))
      .sort((a, b) => b.date_from.localeCompare(a.date_from))
      .map((b) => this.summary(b));
  }

  block(id: string): TriageBlock {
    const { buckets, ...rest } = this.rawBlock(id);
    return {
      ...rest,
      style_name: this.styleName(rest.style_id),
      buckets: buckets.map((bucket) => ({
        id: bucket.id,
        bucket_type: bucket.bucket_type,
        category_id: bucket.category_id,
        category_name: bucket.category_id
          ? (this.s.categories.find((c) => c.id === bucket.category_id)?.name ?? null)
          : null,
        inactive: bucket.inactive,
        track_count: bucket.tracks.length,
      })),
    };
  }

  bucketTracks(blockId: string, bucketId: string, search?: string): BucketTrack[] {
    const bucket = this.rawBlock(blockId).buckets.find((b) => b.id === bucketId);
    if (!bucket) return [];
    return bucket.tracks
      .map((e) => ({ e, t: found(this.tracks.get(e.track_id), 'track') }))
      .filter(({ t }) => matches(t, search))
      .map(({ e, t }) => ({
        track_id: t.id,
        title: t.title,
        mix_name: t.mix_name,
        isrc: t.isrc,
        bpm: t.bpm,
        length_ms: t.length_ms,
        publish_date: t.publish_date,
        spotify_release_date: t.publish_date,
        spotify_id: t.spotify_id,
        release_type: 'single',
        is_ai_suspected: false,
        artists: t.artists.map((a) => ({ ...a, role: 'main' })),
        label_id: t.label.id,
        label_name: t.label.name,
        added_at: e.added_at,
        key_name: t.key_name,
        key_camelot: t.key_camelot,
      }));
  }

  move(blockId: string, fromId: string, toId: string, trackIds: string[]): number {
    const block = this.rawBlock(blockId);
    if (block.status !== 'IN_PROGRESS')
      throw new DemoError(409, 'block_finalized', 'This week is already finalized.');
    const from = this.rawBucket(block, fromId);
    const to = this.rawBucket(block, toId);
    const moving = from.tracks.filter((e) => trackIds.includes(e.track_id));
    from.tracks = from.tracks.filter((e) => !trackIds.includes(e.track_id));
    to.tracks.push(...moving.map((e) => ({ ...e, added_at: NOW() })));
    block.updated_at = NOW();
    return moving.length;
  }

  finalize(blockId: string): FinalizeResponse {
    const block = this.rawBlock(blockId);
    if (block.status !== 'IN_PROGRESS')
      throw new DemoError(409, 'block_finalized', 'This week is already finalized.');
    const promoted: Record<string, number> = {};
    for (const bucket of block.buckets) {
      if (bucket.bucket_type !== 'STAGING' || !bucket.category_id || bucket.inactive) continue;
      const category = this.rawCategory(bucket.category_id);
      let added = 0;
      for (const e of bucket.tracks) {
        if (category.tracks.some((t) => t.track_id === e.track_id)) continue;
        category.tracks.push({
          track_id: e.track_id,
          added_at: NOW(),
          source_triage_block_id: block.id,
        });
        added++;
      }
      promoted[category.id] = added;
    }
    block.status = 'FINALIZED';
    block.finalized_at = block.updated_at = NOW();
    return { block: this.block(block.id), promoted };
  }

  // ── categories ────────────────────────────────────────────────────────────

  private rawCategory(id: string): DemoCategory {
    return found(
      this.s.categories.find((c) => c.id === id),
      'category',
    );
  }

  private categoryOut(c: DemoCategory): Category {
    const { tracks, ...rest } = c;
    return { ...rest, style_name: this.styleName(c.style_id), track_count: tracks.length };
  }

  categoriesByStyle(styleId: string): Category[] {
    return this.s.categories
      .filter((c) => c.style_id === styleId)
      .sort((a, b) => a.position - b.position)
      .map((c) => this.categoryOut(c));
  }

  category(id: string): Category {
    return this.categoryOut(this.rawCategory(id));
  }

  private inPlaylist(trackId: string): boolean {
    return this.s.playlists.some((p) => p.tracks.some((t) => t.track_id === trackId));
  }

  categoryTracks(id: string, q: CategoryTrackQuery): CategoryTrack[] {
    const tagged = (trackId: string) => {
      if (!q.tags?.length) return true;
      const own = this.s.trackTags[trackId] ?? [];
      return q.match === 'any'
        ? q.tags.some((t) => own.includes(t))
        : q.tags.every((t) => own.includes(t));
    };
    const rows = this.rawCategory(id)
      .tracks.map((e) => ({ e, t: found(this.tracks.get(e.track_id), 'track') }))
      .filter(
        ({ t }) => matches(t, q.search) && tagged(t.id) && !(q.fresh && this.inPlaylist(t.id)),
      )
      .map(({ e, t }) => ({
        id: t.id,
        title: t.title,
        mix_name: t.mix_name,
        artists: t.artists,
        label: t.label,
        bpm: t.bpm,
        length_ms: t.length_ms,
        publish_date: t.publish_date,
        spotify_release_date: t.publish_date,
        isrc: t.isrc,
        spotify_id: t.spotify_id,
        release_type: 'single',
        is_ai_suspected: false,
        used_in_playlist: this.inPlaylist(t.id),
        added_at: e.added_at,
        source_triage_block_id: e.source_triage_block_id,
        tags: this.trackTags(t.id),
        key_name: t.key_name,
        key_camelot: t.key_camelot,
      }));
    const key = q.sort ?? 'added_at';
    const sign = (q.order ?? (key === 'title' ? 'asc' : 'desc')) === 'asc' ? 1 : -1;
    const value = (r: CategoryTrack) =>
      key === 'title' ? r.title : key === 'added_at' ? r.added_at : (r.spotify_release_date ?? '');
    return rows.sort((a, b) => sign * value(a).localeCompare(value(b)));
  }

  addToCategory(id: string, trackId: string): Category {
    const category = this.rawCategory(id);
    found(this.tracks.get(trackId), 'track');
    if (!category.tracks.some((t) => t.track_id === trackId)) {
      category.tracks.push({ track_id: trackId, added_at: NOW(), source_triage_block_id: null });
    }
    return this.categoryOut(category);
  }

  removeFromCategory(id: string, trackId: string): void {
    const category = this.rawCategory(id);
    category.tracks = category.tracks.filter((t) => t.track_id !== trackId);
  }

  createCategory(styleId: string, name: string): Category {
    this.styleName(styleId);
    const position = this.s.categories.filter((c) => c.style_id === styleId).length;
    const category: DemoCategory = {
      id: newId('c'),
      style_id: styleId,
      name,
      position,
      created_at: NOW(),
      updated_at: NOW(),
      tracks: [],
    };
    this.s.categories.push(category);
    // Every open week of the style gets a staging bucket for the new category.
    for (const b of this.s.blocks) {
      if (b.style_id !== styleId || b.status !== 'IN_PROGRESS') continue;
      b.buckets.push({
        id: `${b.id}-st-${category.id}`,
        bucket_type: 'STAGING',
        category_id: category.id,
        inactive: false,
        tracks: [],
      });
    }
    return this.categoryOut(category);
  }

  renameCategory(id: string, name: string): Category {
    const category = this.rawCategory(id);
    category.name = name;
    category.updated_at = NOW();
    return this.categoryOut(category);
  }

  deleteCategory(id: string): void {
    this.rawCategory(id);
    this.s.categories = this.s.categories.filter((c) => c.id !== id);
    for (const b of this.s.blocks)
      for (const bucket of b.buckets) if (bucket.category_id === id) bucket.inactive = true;
  }

  reorderCategories(styleId: string, ids: string[]): Category[] {
    ids.forEach((id, position) => {
      const c = this.rawCategory(id);
      if (c.style_id === styleId) c.position = position;
    });
    return this.categoriesByStyle(styleId);
  }

  // ── playlists ─────────────────────────────────────────────────────────────

  private rawPlaylist(id: string): DemoPlaylist {
    return found(
      this.s.playlists.find((p) => p.id === id),
      'playlist',
    );
  }

  private playlistOut(p: DemoPlaylist): Playlist {
    const { tracks, ...rest } = p;
    return {
      ...rest,
      user_id: 'u-demo',
      cover_s3_key: null,
      cover_url: null,
      cover_uploaded_at: null,
      spotify_playlist_id: null,
      last_published_at: null,
      needs_republish: false,
      ytmusic_playlist_id: null,
      ytmusic_last_published_at: null,
      ytmusic_needs_republish: false,
      track_count: tracks.length,
    };
  }

  playlists(q: { status?: PlaylistStatus; search?: string }): Playlist[] {
    return this.s.playlists
      .filter(
        (p) =>
          (!q.status || p.status === q.status) &&
          (!q.search || p.name.toLowerCase().includes(q.search.toLowerCase())),
      )
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
      .map((p) => this.playlistOut(p));
  }

  playlist(id: string): Playlist {
    return this.playlistOut(this.rawPlaylist(id));
  }

  createPlaylist(input: {
    name: string;
    description?: string | null;
    is_public?: boolean;
  }): Playlist {
    const p: DemoPlaylist = {
      id: newId('p'),
      name: input.name,
      description: input.description ?? null,
      is_public: input.is_public ?? true,
      status: 'active',
      created_at: NOW(),
      updated_at: NOW(),
      tracks: [],
    };
    this.s.playlists.push(p);
    return this.playlistOut(p);
  }

  patchPlaylist(
    id: string,
    patch: Partial<Pick<DemoPlaylist, 'name' | 'description' | 'is_public' | 'status'>>,
  ): Playlist {
    const p = this.rawPlaylist(id);
    for (const key of ['name', 'description', 'is_public', 'status'] as const) {
      if (patch[key] !== undefined) Object.assign(p, { [key]: patch[key] });
    }
    p.updated_at = NOW();
    return this.playlistOut(p);
  }

  deletePlaylist(id: string): void {
    this.rawPlaylist(id);
    this.s.playlists = this.s.playlists.filter((p) => p.id !== id);
  }

  playlistTracks(id: string): PlaylistTrack[] {
    return this.rawPlaylist(id).tracks.map((e, position) => {
      const t = found(this.tracks.get(e.track_id), 'track');
      return {
        track_id: t.id,
        position,
        added_at: e.added_at,
        title: t.title,
        spotify_id: t.spotify_id,
        isrc: t.isrc,
        length_ms: t.length_ms,
        origin: 'beatport',
        mix_name: t.mix_name,
        artists: t.artists,
        label: t.label,
        bpm: t.bpm,
        spotify_release_date: t.publish_date,
        is_ai_suspected: false,
        tags: this.trackTags(t.id),
        ytmusic: null,
        key_name: t.key_name,
        key_camelot: t.key_camelot,
      };
    });
  }

  addToPlaylist(id: string, trackIds: string[]): AddTracksResult {
    const p = this.rawPlaylist(id);
    const added: string[] = [];
    const skipped_duplicates: string[] = [];
    for (const trackId of trackIds) {
      found(this.tracks.get(trackId), 'track');
      if (p.tracks.some((t) => t.track_id === trackId)) skipped_duplicates.push(trackId);
      else {
        p.tracks.push({ track_id: trackId, added_at: NOW() });
        added.push(trackId);
      }
    }
    p.updated_at = NOW();
    return { added, skipped_duplicates, position_after: p.tracks.length };
  }

  removeFromPlaylist(id: string, trackId: string): void {
    const p = this.rawPlaylist(id);
    p.tracks = p.tracks.filter((t) => t.track_id !== trackId);
  }

  reorderPlaylist(id: string, trackIds: string[]): void {
    const p = this.rawPlaylist(id);
    const byId = new Map(p.tracks.map((t) => [t.track_id, t]));
    const ordered = trackIds.flatMap((tid) => byId.get(tid) ?? []);
    p.tracks = [...ordered, ...p.tracks.filter((t) => !trackIds.includes(t.track_id))];
  }

  // ── tags ──────────────────────────────────────────────────────────────────

  tags(): Tag[] {
    return [...this.s.tags].sort((a, b) => a.name.localeCompare(b.name));
  }

  private rawTag(id: string): Tag {
    return found(
      this.s.tags.find((t) => t.id === id),
      'tag',
    );
  }

  createTag(name: string, color: string | null): Tag {
    const tag: Tag = { id: newId('tg'), name, color, created_at: NOW(), updated_at: NOW() };
    this.s.tags.push(tag);
    return tag;
  }

  patchTag(id: string, patch: { name?: string; color?: string | null }): Tag {
    const tag = this.rawTag(id);
    if (patch.name !== undefined) tag.name = patch.name;
    if (patch.color !== undefined) tag.color = patch.color;
    tag.updated_at = NOW();
    return tag;
  }

  deleteTag(id: string): void {
    this.rawTag(id);
    this.s.tags = this.s.tags.filter((t) => t.id !== id);
    for (const trackId of Object.keys(this.s.trackTags)) {
      this.s.trackTags[trackId] = (this.s.trackTags[trackId] ?? []).filter((t) => t !== id);
    }
  }

  trackTags(trackId: string): { id: string; name: string; color: string | null }[] {
    return (this.s.trackTags[trackId] ?? []).flatMap((id) => {
      const tag = this.s.tags.find((t) => t.id === id);
      return tag ? [{ id: tag.id, name: tag.name, color: tag.color }] : [];
    });
  }

  tagTrack(trackId: string, tagId: string): { id: string; name: string; color: string | null }[] {
    found(this.tracks.get(trackId), 'track');
    this.rawTag(tagId);
    const own = (this.s.trackTags[trackId] ??= []);
    if (!own.includes(tagId)) own.push(tagId);
    return this.trackTags(trackId);
  }

  untagTrack(trackId: string, tagId: string): void {
    this.s.trackTags[trackId] = (this.s.trackTags[trackId] ?? []).filter((t) => t !== tagId);
  }
}
