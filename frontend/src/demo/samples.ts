/**
 * Sample payloads shared by the demo build and the README screenshots: a month of
 * listening, the curation funnel, time per track, ingest coverage and auto-ingest state.
 * Deterministic, invented, dated October 2026.
 */
import type { CoveragePayload } from '../features/admin/hooks/useCoverage';
import type {
  FunnelResponse,
  ListeningResponse,
  TimePerTrackResponse,
} from '../features/analytics/hooks/useAnalytics';

export const SAMPLE_TODAY = '2026-10-08';

export function sampleListening(): ListeningResponse {
  // A deterministic but irregular month; weekends run longer.
  const daily = Array.from({ length: 30 }, (_, i) => {
    const d = new Date(Date.UTC(2026, 8, 9 + i));
    const weekend = d.getUTCDay() === 0 || d.getUTCDay() === 6;
    const minutes = (weekend ? 70 : 25) + ((i * 37 + i * i * 11) % 41);
    return {
      dt: d.toISOString().slice(0, 10),
      listened_ms: minutes * 60_000,
      tracks: Math.round(minutes / 3.2),
    };
  });
  const total = (days: typeof daily) => ({
    listened_ms: days.reduce((sum, d) => sum + d.listened_ms, 0),
    tracks: days.reduce((sum, d) => sum + d.tracks, 0),
  });
  return {
    today: SAMPLE_TODAY,
    totals: { day: total(daily.slice(-1)), week: total(daily.slice(-7)), month: total(daily) },
    daily,
  };
}

export function sampleFunnel(): FunnelResponse {
  return {
    today: SAMPLE_TODAY,
    stages: [
      { stage: 'triaged', day: 140, week: 912, month: 3810 },
      { stage: 'categorized', day: 31, week: 206, month: 874 },
      { stage: 'playlisted', day: 9, week: 64, month: 251 },
    ],
  };
}

export function sampleTimePerTrack(days = 30): TimePerTrackResponse {
  return {
    days,
    stages: ['triage', 'category', 'playlist'],
    rows: [
      {
        style_id: '*',
        style_name: null,
        cells: {
          triage: { n: 3810, p50_ms: 9_000, p90_ms: 31_000 },
          category: { n: 874, p50_ms: 42_000, p90_ms: 118_000 },
          playlist: { n: 251, p50_ms: 63_000, p90_ms: 171_000 },
        },
      },
      {
        style_id: '81',
        style_name: 'Funky House',
        cells: {
          triage: { n: 1420, p50_ms: 8_000, p90_ms: 27_000 },
          category: { n: 330, p50_ms: 39_000, p90_ms: 104_000 },
          playlist: { n: 97, p50_ms: 58_000, p90_ms: 160_000 },
        },
      },
      {
        style_id: '96',
        style_name: 'Mainstage',
        cells: {
          triage: { n: 1190, p50_ms: 10_000, p90_ms: 35_000 },
          category: { n: 251, p50_ms: 47_000, p90_ms: 131_000 },
          playlist: { n: 72, p50_ms: 69_000, p90_ms: 182_000 },
        },
      },
    ],
  };
}

export const COVERAGE_STYLES = [
  'Funky House',
  'Mainstage',
  'Tech House',
  'Melodic House & Techno',
  'Techno (Peak Time)',
  'Afro House',
];

export function sampleCoverage(weekYear = 2026): CoveragePayload {
  const styles = COVERAGE_STYLES.map((style_name, i) => ({
    style_id: 80 + i,
    clouder_style_id: `cs${i}`,
    style_name,
    is_hidden: false,
    cells: Array.from({ length: 39 }, (_, w) => ({
      week_number: w + 1,
      status: (i === 1 && w === 33) || (i === 4 && w === 20) ? 'failed' : 'completed',
      run_id: `r${i}-${w}`,
      item_count: 180 + ((i * 37 + w * 53) % 1300),
      is_custom_range: false,
      period_start: '2026-01-03',
      period_end: '2026-01-09',
      started_at: '2026-10-07T03:00:00Z',
      finished_at: '2026-10-07T03:03:00Z',
    })),
    spotify_weeks: [],
    // The latest week of each style still has a few YT Music matches to review.
    youtube_weeks: [
      { week_number: 39, total: 40, found: 31, review: 3, not_found: 1, pending: 5 },
    ],
    // Over the 31 matches: the analyzer checked most, profiled fewer.
    analysis_weeks: [{ week_number: 39, total: 31, checked: 28, ai: 5, profiled: 20 }],
  }));
  return { week_year: weekYear, weeks_in_year: 52, styles } as CoveragePayload;
}

const REVIEW_TRACKS = [
  ['Night Drive', 'Extended Mix', 'Marlo Vance', 390000],
  ['Glasshouse', 'Original Mix', 'Ines Kord', 412000],
  ['Low Orbit', 'Dub Mix', 'Tavi Rhee', 365000],
] as const;

/** A demo cell's open YT Music reviews: the short edit and a remix, best first. */
export function sampleYoutubeReview(styleId: number, weekYear: number, weekNumber: number) {
  const i = styleId - 80;
  const style_name = COVERAGE_STYLES[i] ?? null;
  const tracks = REVIEW_TRACKS.map(([title, mix, artist, length], n) => ({
    track_id: `yt-review-${styleId}-${weekNumber}-${n}`,
    title,
    mix_name: mix,
    artists: artist,
    length_ms: length,
    spotify_url: null,
    candidates: [
      { suffix: '', seconds: 201, score: 0.9 },
      { suffix: ' (Remix)', seconds: length / 1000 - 20, score: 0.72 },
      { suffix: ' (Radio Edit)', seconds: 188, score: 0.68 },
      { suffix: ' (Live)', seconds: length / 1000 + 41, score: 0.61 },
      { suffix: ' (Acapella)', seconds: 96, score: 0.55 },
    ].map((c, k) => {
      const id = `demo${n}${k}${String(styleId).padStart(4, '0')}`.slice(0, 11);
      return {
        vendor_track_id: id,
        title: `${title}${c.suffix}`,
        artists: [artist],
        album: null,
        duration_ms: c.seconds * 1000,
        url: `https://music.youtube.com/watch?v=${id}`,
        score: c.score,
      };
    }),
  }));
  return { style_name, week_year: weekYear, week_number: weekNumber, tracks };
}

export function sampleAutoIngest() {
  // Today's three random runs: the first went 4 hours ago, two are ahead.
  const at = (hours: number) => new Date(Date.now() + hours * 3_600_000).toISOString();
  return {
    running: false,
    settings: {
      enabled: true,
      mode: 'random',
      fixed_times: ['09:00', '15:00', '21:00'],
      runs_per_day: 3,
      timezone: 'UTC',
      periods_per_run: 3,
      backfill_floor: '2026-01-03',
      updated_at: '2026-10-08T06:00:00+00:00',
    },
    planned_runs: [at(-4), at(3), at(9)],
    last_run: {
      at: at(-4),
      manual: false,
      ok: true,
      pairs: [
        { style_id: 80, week_year: 2026, week_number: 38, ok: true, run_id: 'r1', item_count: 300 },
        { style_id: 81, week_year: 2026, week_number: 38, ok: true, run_id: 'r2', item_count: 889 },
        {
          style_id: 82,
          week_year: 2026,
          week_number: 38,
          ok: true,
          run_id: 'r3',
          item_count: 1465,
        },
      ],
    },
    due_week: { week_year: 2026, week_number: 39 },
    stuck: [],
  };
}

const DAY_MS = 86_400_000;
const NO_MODEL = {
  version: 0,
  trained_at: null,
  n_labels: null,
  n_keep: null,
  rows_total: null,
  keep_auc: null,
  category_bacc: null,
  n_classes: null,
  first_hit: null,
  first_n: null,
  max_rss_mb: null,
  predictions: 0,
};

/** The admin "Suggestion models" table: three trained models (one near the memory cap, one
 * capped at the training row limit), a queued retrain and a pair still collecting labels. */
export function sampleSuggestionModels() {
  const ago = (days: number) => new Date(Date.now() - days * DAY_MS).toISOString();
  const pair = (user: [string, string], style: [string, string]) => ({
    user_id: user[0],
    user_name: user[1],
    style_id: style[0],
    style_name: style[1],
    retrain_pending: false,
    labels_since_training: null,
  });
  const demo: [string, string] = ['u-demo', 'Demo DJ'];
  const mara: [string, string] = ['u-mara', 'Mara K'];
  return [
    {
      ...pair(demo, ['s-afro', 'Afro House']),
      version: 2,
      trained_at: ago(5),
      n_labels: 310,
      n_keep: 122,
      rows_total: 310,
      keep_auc: 0.776,
      category_bacc: 0.534,
      n_classes: 3,
      first_hit: 0.5,
      first_n: 14,
      max_rss_mb: 1460,
      predictions: 2050,
    },
    {
      ...pair(demo, ['s-melodic', 'Melodic House & Techno']),
      version: 4,
      trained_at: ago(2),
      n_labels: 1200,
      n_keep: 410,
      rows_total: 1840,
      keep_auc: 0.842,
      category_bacc: 0.611,
      n_classes: 3,
      first_hit: 0.58,
      first_n: 64,
      max_rss_mb: 2710,
      predictions: 3120,
    },
    { ...pair(demo, ['s-deep', 'Minimal / Deep Tech']), ...NO_MODEL, labels_since_training: 62 },
    { ...pair(mara, ['s-prog', 'Progressive House']), ...NO_MODEL, retrain_pending: true },
    {
      ...pair(mara, ['s-techno', 'Techno (Peak Time)']),
      version: 1,
      trained_at: ago(9),
      n_labels: 180,
      n_keep: 64,
      rows_total: 180,
      keep_auc: 0.701,
      category_bacc: null,
      n_classes: null,
      first_hit: null,
      first_n: 0,
      max_rss_mb: 1210,
      predictions: 980,
    },
  ];
}

/**
 * A made-up wave-1 waveform (GET /tracks/{id}/waveform), the same for a track every time:
 * intro, groove, break, drop, breakdown, outro, with the edges moved per track. Every
 * fourth track has none, like a track the analyzer has not read yet.
 */
export function sampleWaveform(trackId: string) {
  let seed = [...trackId].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
  const rand = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 2 ** 32;
  };
  if (seed % 4 === 0) return { waveform: null };
  const n = 600;
  const at = (x: number) => Math.round(x * n);
  const breakStart = at(0.3 + 0.1 * rand());
  const dropStart = breakStart + at(0.08 + 0.05 * rand());
  const downStart = at(0.72 + 0.08 * rand());
  const outroStart = at(0.88);
  const bass = (i: number) => {
    if (i < at(0.08)) return 150;
    if (i < breakStart) return 232;
    if (i < dropStart) return 40 + (60 * (i - breakStart)) / (dropStart - breakStart);
    if (i < downStart) return 250;
    if (i < outroStart) return 120;
    return 220 - (160 * (i - outroStart)) / (n - outroStart);
  };
  const low = Array.from({ length: n }, (_, i) => bass(i) + 10 * (rand() - 0.5));
  const mid = low.map((v) => 0.6 * v + 60 + 20 * rand());
  const high = mid.map((v) => 0.8 * v);
  const bytes = [...low, ...mid, ...high].map((v) => Math.max(0, Math.min(255, Math.round(v))));
  return { waveform: { duration_ms: 360_000, data: btoa(String.fromCharCode(...bytes)) } };
}
