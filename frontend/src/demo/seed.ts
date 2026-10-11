/**
 * The demo's sample catalog: three styles, a finalized and an open triage week each,
 * categories, playlists and tags. Everything is invented and seeded, so every visitor
 * sees the same week.
 */
import type { BucketType } from '../features/triage/lib/bucketLabels';
import type { TriageStatus } from '../features/triage/hooks/useTriageBlocksByStyle';
import type { PlaylistStatus } from '../features/playlists/lib/playlistTypes';
import type { Tag } from '../features/tags/hooks/useTags';

export interface DemoTrack {
  id: string;
  style_id: string;
  title: string;
  mix_name: string;
  artists: { id: string; name: string }[];
  label: { id: string; name: string };
  bpm: number;
  length_ms: number;
  publish_date: string;
  isrc: string;
  spotify_id: string;
  key_name: string;
  key_camelot: string;
}

export interface DemoEntry {
  track_id: string;
  added_at: string;
}

export interface DemoBucket {
  id: string;
  bucket_type: BucketType;
  category_id: string | null;
  inactive: boolean;
  tracks: DemoEntry[];
}

export interface DemoBlock {
  id: string;
  style_id: string;
  name: string;
  date_from: string;
  date_to: string;
  status: TriageStatus;
  created_at: string;
  updated_at: string;
  finalized_at: string | null;
  buckets: DemoBucket[];
}

export interface DemoCategory {
  id: string;
  style_id: string;
  name: string;
  position: number;
  created_at: string;
  updated_at: string;
  tracks: (DemoEntry & { source_triage_block_id: string | null })[];
}

export interface DemoPlaylist {
  id: string;
  name: string;
  description: string | null;
  is_public: boolean;
  status: PlaylistStatus;
  created_at: string;
  updated_at: string;
  tracks: DemoEntry[];
}

export interface DemoStyle {
  id: string;
  name: string;
}

export interface DemoSeed {
  styles: DemoStyle[];
  selected: string[];
  tracks: DemoTrack[];
  blocks: DemoBlock[];
  categories: DemoCategory[];
  playlists: DemoPlaylist[];
  tags: Tag[];
  trackTags: Record<string, string[]>;
}

const STYLES: (DemoStyle & { bpm: number; categories: string[] })[] = [
  { id: 's-tech', name: 'Tech House', bpm: 125, categories: ['Warm-up', 'Peak time', 'Closing'] },
  {
    id: 's-melodic',
    name: 'Melodic House & Techno',
    bpm: 121,
    categories: ['Opening', 'Journey', 'Afterhours'],
  },
  { id: 's-afro', name: 'Afro House', bpm: 119, categories: ['Percussive', 'Vocal', 'Deep'] },
];
const OTHER_STYLES: DemoStyle[] = [
  { id: 's-techno', name: 'Techno (Peak Time)' },
  { id: 's-deep', name: 'Minimal / Deep Tech' },
  { id: 's-prog', name: 'Progressive House' },
];
const FIRST = [
  'Mara',
  'Odessa',
  'Kai',
  'Lumen',
  'Ines',
  'Teo',
  'Ravi',
  'Noor',
  'Sasha',
  'Juno',
  'Elio',
  'Vera',
  'Nils',
  'Zara',
];
const LAST = [
  'Quill',
  'Lane',
  'Arden',
  'Vos',
  'Halden',
  'Marlo',
  'Sable',
  'Reyes',
  'Okafor',
  'Lind',
  'Moreau',
  'Tanaka',
];
const WORDS = [
  'Night',
  'Drive',
  'Velvet',
  'Signal',
  'Tide',
  'Echo',
  'Afterglow',
  'Pulse',
  'Mirage',
  'Static',
  'Orbit',
  'Ember',
  'Harbor',
  'Neon',
  'Glass',
  'Fever',
  'Shadow',
  'Bloom',
  'Circuit',
  'Haze',
  'Ritual',
  'Sunday',
  'Copper',
  'Lantern',
  'Drift',
  'Marble',
  'Saffron',
  'Thunder',
];
const MIXES = ['Original Mix', 'Extended Mix', 'Dub', 'Club Mix'];
const LABELS = [
  'Lowtide Records',
  'Northbound',
  'Palette Audio',
  'Coral Tapes',
  'Hinterland',
  'Dense Grid',
];
const KEYS: [string, string][] = [
  ['A minor', '8A'],
  ['C major', '8B'],
  ['F minor', '4A'],
  ['G minor', '6A'],
  ['D minor', '7A'],
  ['E minor', '9A'],
  ['B♭ minor', '3A'],
  ['F♯ minor', '11A'],
];
const BASE62 = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
const TRACKS_PER_STYLE = 48;
const OPEN_WEEK = { name: 'Week 41 · Oct 3 – 9', from: '2026-10-03', to: '2026-10-09' };
const PAST_WEEK = { name: 'Week 40 · Sep 26 – Oct 2', from: '2026-09-26', to: '2026-10-02' };

// mulberry32: small, fast and seedable.
function rng(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** xs[i], or a loud failure — the seed's indexes are fixed, so this never throws. */
function item<T>(xs: readonly T[], i: number): T {
  const x = xs[i];
  if (x === undefined) throw new Error(`seed index ${i} out of range`);
  return x;
}

const at = (date: string, hour: number) => `${date}T${String(hour % 24).padStart(2, '0')}:00:00Z`;

export function buildSeed(): DemoSeed {
  const rand = rng(2026);
  const pick = <T>(xs: readonly T[]): T => item(xs, Math.floor(rand() * xs.length));
  const artists = Array.from({ length: 24 }, (_, i) => ({
    id: `a-${i}`,
    name: `${FIRST[i % FIRST.length]} ${LAST[(i * 5) % LAST.length]}`,
  }));
  const labels = LABELS.map((name, i) => ({ id: `l-${i}`, name }));

  const tracks: DemoTrack[] = [];
  const blocks: DemoBlock[] = [];
  const categories: DemoCategory[] = [];

  STYLES.forEach((style, si) => {
    const ids: string[] = [];
    for (let n = 0; n < TRACKS_PER_STYLE; n++) {
      const open = n < 30;
      const [key_name, key_camelot] = pick(KEYS);
      const main = pick(artists);
      const second = rand() < 0.3 ? pick(artists) : null;
      const day = open ? 3 + (n % 7) : 26 + (n % 5);
      const month = open ? '10' : '09';
      const id = `t-${si}-${n}`;
      ids.push(id);
      tracks.push({
        id,
        style_id: style.id,
        title: `${pick(WORDS)} ${pick(WORDS)}`,
        mix_name: pick(MIXES),
        artists: second && second.id !== main.id ? [main, second] : [main],
        label: pick(labels),
        bpm: style.bpm - 2 + Math.floor(rand() * 5),
        length_ms: (330 + Math.floor(rand() * 120)) * 1000,
        publish_date: `2026-${month}-${String(day).padStart(2, '0')}`,
        isrc: `QZDA6${String(26000 + si * 100 + n).padStart(7, '0')}`,
        spotify_id: Array.from({ length: 22 }, () => pick([...BASE62])).join(''),
        key_name,
        key_camelot,
      });
    }

    const cats = style.categories.map((name, ci) => ({
      id: `c-${si}-${ci}`,
      style_id: style.id,
      name,
      position: ci,
      created_at: at('2026-09-12', 10 + ci),
      updated_at: at('2026-10-02', 18),
      tracks: [] as DemoCategory['tracks'],
    }));
    categories.push(...cats);

    const past = `b-${si}-40`;
    const open = `b-${si}-41`;
    const entry = (track_id: string, date: string, h: number) => ({
      track_id,
      added_at: at(date, h),
    });
    // The past week's 18 tracks were finalized into the three categories, 6 each.
    ids.slice(30).forEach((id, k) =>
      item(cats, k % 3).tracks.push({
        ...entry(id, '2026-10-02', 12 + (k % 6)),
        source_triage_block_id: past,
      }),
    );

    const staging = (blockId: string, withTracks: DemoEntry[][]) =>
      cats.map((c, ci) => ({
        id: `${blockId}-st-${ci}`,
        bucket_type: 'STAGING' as const,
        category_id: c.id,
        inactive: false,
        tracks: withTracks[ci] ?? [],
      }));
    const tech = (blockId: string, counts: Record<string, string[]>): DemoBucket[] =>
      (['NEW', 'OLD', 'NOT', 'UNCLASSIFIED', 'FAV', 'DISCARD'] as const).map((type) => ({
        id: `${blockId}-${type.toLowerCase()}`,
        bucket_type: type,
        category_id: null,
        inactive: false,
        tracks: (counts[type] ?? []).map((id, k) => entry(id, '2026-10-09', 9 + (k % 8))),
      }));

    blocks.push({
      id: past,
      style_id: style.id,
      name: PAST_WEEK.name,
      date_from: PAST_WEEK.from,
      date_to: PAST_WEEK.to,
      status: 'FINALIZED',
      created_at: at('2026-10-02', 8),
      updated_at: at('2026-10-02', 19),
      finalized_at: at('2026-10-02', 19),
      buckets: [
        ...tech(past, {}),
        ...staging(
          past,
          [0, 1, 2].map((ci) =>
            item(cats, ci).tracks.map(({ track_id, added_at }) => ({ track_id, added_at })),
          ),
        ),
      ],
    });
    const fresh = ids.slice(0, 30);
    blocks.push({
      id: open,
      style_id: style.id,
      name: OPEN_WEEK.name,
      date_from: OPEN_WEEK.from,
      date_to: OPEN_WEEK.to,
      status: 'IN_PROGRESS',
      created_at: at('2026-10-09', 8),
      updated_at: at('2026-10-09', 17),
      finalized_at: null,
      buckets: [
        ...tech(open, {
          NEW: fresh.slice(0, 18),
          OLD: fresh.slice(18, 23),
          NOT: fresh.slice(23, 26),
          UNCLASSIFIED: fresh.slice(26, 28),
          FAV: fresh.slice(28, 29),
        }),
        ...staging(open, [[], [entry(item(fresh, 29), '2026-10-09', 16)]]),
      ],
    });
  });

  const fromCategory = (ci: number, n: number, date: string) =>
    item(categories, ci)
      .tracks.slice(0, n)
      .map((t, k) => ({ track_id: t.track_id, added_at: at(date, 10 + k) }));
  const playlists: DemoPlaylist[] = [
    {
      id: 'p-warmup',
      name: 'Saturday warm-up',
      description: 'First hour: groove before energy.',
      is_public: true,
      status: 'active',
      created_at: at('2026-10-03', 11),
      updated_at: at('2026-10-09', 20),
      tracks: [...fromCategory(0, 4, '2026-10-04'), ...fromCategory(3, 2, '2026-10-05')],
    },
    {
      id: 'p-peak',
      name: 'Peak hour ideas',
      description: null,
      is_public: false,
      status: 'active',
      created_at: at('2026-10-05', 12),
      updated_at: at('2026-10-08', 21),
      tracks: [...fromCategory(1, 4, '2026-10-06'), ...fromCategory(6, 2, '2026-10-07')],
    },
    {
      id: 'p-september',
      name: 'September set',
      description: 'Played on Sep 27.',
      is_public: true,
      status: 'completed',
      created_at: at('2026-09-20', 15),
      updated_at: at('2026-09-27', 23),
      tracks: [...fromCategory(2, 2, '2026-09-21'), ...fromCategory(8, 2, '2026-09-22')],
    },
  ];
  const TAGS: [string, string, string][] = [
    ['tg-vocal', 'Vocal', '#e8590c'],
    ['tg-groovy', 'Groovy', '#2f9e44'],
    ['tg-dark', 'Dark', '#5f3dc4'],
    ['tg-hypnotic', 'Hypnotic', '#1971c2'],
  ];
  const tags: Tag[] = TAGS.map(([id, name, color]) => ({
    id,
    name,
    color,
    created_at: at('2026-09-12', 9),
    updated_at: at('2026-09-12', 9),
  }));
  const trackTags: Record<string, string[]> = {};
  categories.forEach((c, ci) =>
    c.tracks
      .slice(0, 2)
      .forEach((t, k) => (trackTags[t.track_id] = [item(tags, (ci + k) % tags.length).id])),
  );

  return {
    styles: [...STYLES.map(({ id, name }) => ({ id, name })), ...OTHER_STYLES],
    selected: STYLES.map((s) => s.id),
    tracks,
    blocks,
    categories,
    playlists,
    tags,
    trackTags,
  };
}
