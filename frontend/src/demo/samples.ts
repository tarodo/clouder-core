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
  }));
  return { week_year: weekYear, weeks_in_year: 52, styles } as CoveragePayload;
}

export function sampleAutoIngest() {
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
    planned_runs: [
      '2026-10-08T09:41:00+00:00',
      '2026-10-08T15:12:00+00:00',
      '2026-10-08T22:37:00+00:00',
    ],
    last_run: {
      at: '2026-10-08T03:50:00+00:00',
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
