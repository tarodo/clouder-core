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
import type { ArtistDetail, ArtistsListResponse, ArtistSummary } from '../api/artists';
import type { LabelDetail, LabelsListResponse, LabelSummary } from '../api/labels';
import { slugifyStyle } from '../features/library/lib/slugifyStyle';
import { clipOf } from './clips';
import { demoCover } from './covers';
import { LABEL_PROFILES } from './profiles';

const idHash = (id: string): number => [...id].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);

// A few demo tracks carry each AI level so every badge color shows up.
const aiVerdict = (id: string): 'high' | 'medium' | 'low' | null => {
  const h = idHash(id) % 12;
  return h === 0 ? 'high' : h === 1 ? 'medium' : h === 2 ? 'low' : null;
};

// The demo user's recommender, so the block page shows its model line.
const DEMO_MODEL: NonNullable<TriageBlock['model']> = {
  trained_at: '2026-10-09T03:00:00Z',
  n_labels: 1240,
  first_hit: 0.68,
  first_n: 57,
};

export interface LibraryQuery {
  /** Style id; the list shows who has tracks in it. */
  style?: string;
  q?: string;
  sort?: 'name' | 'recent';
  my?: 'liked' | 'disliked' | 'unrated';
  page?: number;
  limit?: number;
}

type Preference = 'liked' | 'disliked';
const PROFILE_UPDATED = '2026-10-01T09:00:00Z';
const coverOf = (t: DemoTrack): string | null => (t.cover === null ? null : demoCover(t.cover));

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
      model: DEMO_MODEL,
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
        ai_verdict: aiVerdict(t.id),
        spotify_id: t.spotify_id,
        release_type: 'single',
        artists: t.artists.map((a) => ({ ...a, role: 'main' })),
        label_id: t.label.id,
        label_name: t.label.name,
        added_at: e.added_at,
        key_name: t.key_name,
        key_camelot: t.key_camelot,
        cover_url: coverOf(t),
        prediction: this.prediction(t),
      }));
  }

  // Most tracks get a suggestion, some a discard call and some an unsure one, so every way the
  // buttons light shows on both screens.
  private prediction(t: DemoTrack): BucketTrack['prediction'] {
    const h = idHash(t.id);
    if (h % 5 === 4) return null;
    const ids = this.s.categories.filter((c) => c.style_id === t.style_id).map((c) => c.id);
    const k = h % ids.length;
    return {
      keep: h % 5 === 0 ? false : h % 5 === 3 ? null : true,
      category_ids: [...ids.slice(k), ...ids.slice(0, k)],
      unsure: h % 5 === 2,
    };
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
        ai_verdict: aiVerdict(t.id),
        isrc: t.isrc,
        spotify_id: t.spotify_id,
        release_type: 'single',
        used_in_playlist: this.inPlaylist(t.id),
        added_at: e.added_at,
        source_triage_block_id: e.source_triage_block_id,
        tags: this.trackTags(t.id),
        key_name: t.key_name,
        key_camelot: t.key_camelot,
        cover_url: coverOf(t),
      }));
    const key = q.sort ?? 'added_at';
    const sign = (q.order ?? (key === 'title' ? 'asc' : 'desc')) === 'asc' ? 1 : -1;
    const value = (r: CategoryTrack) =>
      key === 'title' ? r.title : key === 'added_at' ? r.added_at : (r.spotify_release_date ?? '');
    // Ties break on track id like the API, so an undone removal returns to its place.
    return rows.sort((a, b) => sign * value(a).localeCompare(value(b)) || a.id.localeCompare(b.id));
  }

  addToCategory(
    id: string,
    trackId: string,
    restore: { added_at?: string; source_triage_block_id?: string } = {},
  ): Category {
    const category = this.rawCategory(id);
    found(this.tracks.get(trackId), 'track');
    if (!category.tracks.some((t) => t.track_id === trackId)) {
      category.tracks.push({
        track_id: trackId,
        added_at: restore.added_at ?? NOW(),
        source_triage_block_id: restore.source_triage_block_id ?? null,
      });
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
      cover_url: p.cover === null ? null : demoCover(p.cover),
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
      cover: null,
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
        ai_verdict: aiVerdict(t.id),
        tags: this.trackTags(t.id),
        ytmusic: null,
        key_name: t.key_name,
        key_camelot: t.key_camelot,
        cover_url: coverOf(t),
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

  // ── library: labels and artists ──────────────────────────────────────────

  private readonly labelPrefs = new Map<string, Preference>();
  private readonly artistPrefs = new Map<string, Preference>();

  private stylesOf(tracks: DemoTrack[]): string[] {
    const ids = new Set(tracks.map((t) => t.style_id));
    return this.s.styles.filter((st) => ids.has(st.id)).map((st) => st.name);
  }

  /** Who has tracks in the asked style, filtered, sorted and paged like the API. */
  private library<T extends { id: string; name: string }>(
    people: T[],
    owns: (id: string, t: DemoTrack) => boolean,
    prefs: Map<string, Preference>,
    q: LibraryQuery,
  ): {
    total: number;
    page: number;
    limit: number;
    rows: { who: T; tracks: DemoTrack[]; style: string }[];
  } {
    // The Library route carries a slug of the style name; ids work too.
    const style = q.style
      ? this.s.styles.find((st) => st.id === q.style || slugifyStyle(st.name) === q.style)
      : undefined;
    if (q.style && !style) return { total: 0, page: 1, limit: q.limit ?? 50, rows: [] };
    const styleName = style?.name;
    const rows = people
      .map((who) => {
        const tracks = this.s.tracks.filter(
          (t) => owns(who.id, t) && (!style || t.style_id === style.id),
        );
        return { who, tracks, style: styleName ?? this.stylesOf(tracks)[0] ?? '' };
      })
      .filter(({ who, tracks }) => {
        if (!tracks.length) return false;
        if (q.q && !who.name.toLowerCase().includes(q.q.toLowerCase())) return false;
        const pref = prefs.get(who.id);
        return !q.my || (q.my === 'unrated' ? !pref : pref === q.my);
      })
      .sort((a, b) => {
        if (q.sort !== 'recent') return a.who.name.localeCompare(b.who.name);
        const latest = (r: { tracks: DemoTrack[] }) =>
          r.tracks
            .map((t) => t.publish_date)
            .sort()
            .at(-1) ?? '';
        return latest(b).localeCompare(latest(a));
      });
    const page = Math.max(1, q.page ?? 1);
    const limit = Math.max(1, q.limit ?? 50);
    return { total: rows.length, page, limit, rows: rows.slice((page - 1) * limit, page * limit) };
  }

  private rawLabel(id: string) {
    const label = found(
      this.s.labels.find((l) => l.id === id),
      'label',
    );
    return { label, profile: found(LABEL_PROFILES[label.name], 'label') };
  }

  labels(q: LibraryQuery): LabelsListResponse {
    const { rows, ...pageInfo } = this.library(
      this.s.labels,
      (id, t) => t.label.id === id,
      this.labelPrefs,
      q,
    );
    const items: LabelSummary[] = rows.map(({ who, tracks, style }) => {
      const { profile } = this.rawLabel(who.id);
      return {
        id: who.id,
        name: who.name,
        style,
        status: 'completed',
        track_count: tracks.length,
        info: {
          tagline: profile.tagline,
          country: profile.country,
          founded_year: profile.founded_year,
          primary_styles: this.stylesOf(this.s.tracks.filter((t) => t.label.id === who.id)),
          activity: 'steady',
          ai_content: 'none_detected',
          updated_at: PROFILE_UPDATED,
        },
        my_preference: this.labelPrefs.get(who.id) ?? null,
      };
    });
    return { items, ...pageInfo };
  }

  labelDetail(id: string): LabelDetail {
    const { label, profile } = this.rawLabel(id);
    const tracks = this.s.tracks.filter((t) => t.label.id === id);
    const counts = new Map<string, number>();
    for (const t of tracks)
      for (const a of t.artists) counts.set(a.name, (counts.get(a.name) ?? 0) + 1);
    return {
      label_name: label.name,
      tagline: profile.tagline,
      summary: profile.summary,
      country: profile.country,
      founded_year: profile.founded_year,
      notable_artists: [...counts.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 4)
        .map(([name]) => name),
      primary_styles: this.stylesOf(tracks),
      secondary_styles: profile.secondary_styles,
      my_preference: this.labelPrefs.get(id) ?? null,
    };
  }

  setLabelPreference(id: string, status: Preference | 'none'): void {
    this.rawLabel(id);
    if (status === 'none') this.labelPrefs.delete(id);
    else this.labelPrefs.set(id, status);
  }

  private rawArtist(id: string) {
    const artist = found(
      this.s.artists.find((a) => a.id === id),
      'artist',
    );
    return { artist, profile: found(this.s.artistProfiles[id], 'artist') };
  }

  artists(q: LibraryQuery): ArtistsListResponse {
    const owns = (id: string, t: DemoTrack) => t.artists.some((a) => a.id === id);
    const { rows, ...pageInfo } = this.library(this.s.artists, owns, this.artistPrefs, q);
    const items: ArtistSummary[] = rows.map(({ who, tracks, style }) => {
      const { profile } = this.rawArtist(who.id);
      return {
        id: who.id,
        name: who.name,
        style,
        status: 'completed',
        track_count: tracks.length,
        info: {
          tagline: profile.tagline,
          country: profile.country,
          active_since: profile.active_since,
          primary_styles: this.stylesOf(this.s.tracks.filter((t) => owns(who.id, t))),
          artist_type: profile.artist_type,
          ai_content: 'none_detected',
          updated_at: PROFILE_UPDATED,
        },
        my_preference: this.artistPrefs.get(who.id) ?? null,
      };
    });
    return { items, ...pageInfo };
  }

  artistDetail(id: string): ArtistDetail {
    const { artist, profile } = this.rawArtist(id);
    const tracks = this.s.tracks.filter((t) => t.artists.some((a) => a.id === id));
    const collaborators = new Set(
      tracks.flatMap((t) => t.artists.map((a) => a.name)).filter((n) => n !== artist.name),
    );
    return {
      artist_name: artist.name,
      tagline: profile.tagline,
      summary: profile.summary,
      bio: profile.bio,
      country: profile.country,
      active_since: profile.active_since,
      artist_type: profile.artist_type,
      notable_collaborators: [...collaborators].slice(0, 4),
      primary_styles: this.stylesOf(tracks),
      secondary_styles: [],
      my_preference: this.artistPrefs.get(id) ?? null,
    };
  }

  setArtistPreference(id: string, status: Preference | 'none'): void {
    this.rawArtist(id);
    if (status === 'none') this.artistPrefs.delete(id);
    else this.artistPrefs.set(id, status);
  }

  // ── playback ─────────────────────────────────────────────────────────────

  /** File name of the preview clip that plays for a track, or null. */
  clipFor(spotifyId: string): string | null {
    const track = this.s.tracks.find((t) => t.spotify_id === spotifyId);
    return track ? (clipOf(track.style_id, track.id)?.file ?? null) : null;
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
