/**
 * README screenshots: the app's real components rendered with sample data.
 * Run from frontend/: `pnpm screenshots` → docs/assets/*.png.
 * The live app sits behind a Spotify allow-list, so this is how the README shows it.
 */
import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { page } from '@vitest/browser/context';
import { MemoryRouter } from 'react-router';
import { MantineProvider, Paper, SimpleGrid, Stack } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeAll, beforeEach, describe, expect, test } from 'vitest';
import '@mantine/charts/styles.css';
import '../i18n';
import { clouderTheme } from '../theme';
import { CurateCard } from '../features/curate/components/CurateCard';
import { DestinationGrid } from '../features/curate/components/DestinationGrid';
import { BucketGrid } from '../features/triage/components/BucketGrid';
import type { TriageBucket } from '../features/triage/lib/bucketLabels';
import type { BucketTrack } from '../features/triage/hooks/useBucketTracks';
import { CoverageMatrix } from '../features/admin/components/CoverageMatrix';
import type { CoveragePayload } from '../features/admin/hooks/useCoverage';
import { AutoIngestPanel } from '../features/admin/components/AutoIngestPanel';
import { AUTO_INGEST_KEY } from '../features/admin/hooks/useAutoIngest';
import { FunnelCard, ListeningCard, TimePerTrackCard } from '../features/analytics/components/AnalyticsCards';
import { tzOffsetMin } from '../features/analytics/hooks/useAnalytics';

const OUT = '../../../docs/assets';

function client(seed: (qc: QueryClient) => void = () => {}): QueryClient {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  seed(qc);
  return qc;
}

function Frame({ qc, width, children }: { qc: QueryClient; width: number; children: ReactNode }) {
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider theme={clouderTheme} defaultColorScheme="light">
        <MemoryRouter>
          <div data-testid="frame" style={{ width, padding: 24, background: 'var(--color-bg, #fff)' }}>
            {children}
          </div>
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>
  );
}

async function shoot(name: string): Promise<void> {
  // Font faces load lazily; ask for the ones the UI uses before taking the picture.
  await Promise.all(['400 14px "Geist"', '600 14px "Geist"', '400 14px "Geist Mono"', '600 14px "Geist Mono"']
    .map((font) => document.fonts.load(font)));
  await document.fonts.ready;
  const shot = await page.screenshot({ element: screen.getByTestId('frame'), path: `${OUT}/${name}.png`, base64: true });
  expect(shot.base64.length * 0.75).toBeGreaterThan(10_000);
}

const bucket = (id: string, bucket_type: TriageBucket['bucket_type'], track_count: number,
  category_name: string | null = null): TriageBucket =>
  ({ id, bucket_type, track_count, inactive: false, category_id: category_name ? `c-${id}` : null, category_name });

const BUCKETS: TriageBucket[] = [
  bucket('new', 'NEW', 312), bucket('old', 'OLD', 97), bucket('not', 'NOT', 41),
  bucket('unc', 'UNCLASSIFIED', 18), bucket('fav', 'FAV', 6), bucket('dis', 'DISCARD', 120),
  bucket('s1', 'STAGING', 12, 'Warm-up'), bucket('s2', 'STAGING', 8, 'Peak time'),
  bucket('s3', 'STAGING', 5, 'Closing'), bucket('s4', 'STAGING', 9, 'Vocals'),
];

const TRACK: BucketTrack = {
  track_id: 't1', title: 'Night Drive', mix_name: 'Extended Mix', isrc: 'GBXXX2600001',
  bpm: 124, length_ms: 372_000, publish_date: '2026-09-29', spotify_release_date: '2026-09-29',
  spotify_id: 'sp1', release_type: 'single', is_ai_suspected: false,
  artists: [{ id: 'a1', name: 'Mara Quill', role: 'main' }, { id: 'a2', name: 'Odessa Lane', role: 'main' }],
  label_id: 'l1', label_name: 'Lowtide Records', added_at: '2026-10-03T09:00:00Z',
  key_name: 'A minor', key_camelot: '8A',
};

// The test pipeline drops tokens.css's remote @import; link the same Google Fonts URL.
const FONTS = 'https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=Geist+Mono:wght@400;500;600&display=swap';

beforeAll(async () => {
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = FONTS;
  const loaded = new Promise((resolve) => { link.onload = resolve; link.onerror = resolve; });
  document.head.appendChild(link);
  await loaded;
});

beforeEach(async () => {
  await page.viewport(1800, 1000);
});

describe('README screenshots', () => {
  test('curate', async () => {
    render(
      <Frame qc={client()} width={760}>
        <Stack gap="lg">
          <CurateCard track={TRACK} />
          <DestinationGrid buckets={BUCKETS} currentBucketId="new" lastTappedBucketId="s2"
            forceMode={false} onAssign={() => {}} onToggleForce={() => {}} />
        </Stack>
      </Frame>,
    );
    await screen.findByText('Night Drive');
    await shoot('curate');
  });

  test('triage', async () => {
    render(
      <Frame qc={client()} width={1100}>
        <BucketGrid buckets={BUCKETS} styleId="st1" blockId="b1" />
      </Frame>,
    );
    await screen.findByText('Peak time');
    await shoot('triage');
  });

  test('coverage', async () => {
    const styles = ['Funky House', 'Mainstage', 'Tech House', 'Melodic House & Techno', 'Techno (Peak Time)', 'Afro House']
      .map((style_name, i) => ({
        style_id: 80 + i, clouder_style_id: `cs${i}`, style_name, is_hidden: false,
        cells: Array.from({ length: 39 }, (_, w) => ({
          week_number: w + 1,
          status: (i === 1 && w === 33) || (i === 4 && w === 20) ? 'failed' : 'completed',
          run_id: `r${i}-${w}`, item_count: 180 + ((i * 37 + w * 53) % 1300), is_custom_range: false,
          period_start: '2026-01-03', period_end: '2026-01-09',
          started_at: '2026-10-07T03:00:00Z', finished_at: '2026-10-07T03:03:00Z',
        })),
        spotify_weeks: [],
      }));
    const coverage: CoveragePayload = { week_year: 2026, weeks_in_year: 52, styles };
    const qc = client((c) => c.setQueryData(AUTO_INGEST_KEY, {
      running: false,
      settings: {
        enabled: true, mode: 'random', fixed_times: ['09:00', '15:00', '21:00'], runs_per_day: 3,
        timezone: 'UTC', periods_per_run: 3, backfill_floor: '2026-01-03', updated_at: '2026-10-08T06:00:00+00:00',
      },
      planned_runs: ['2026-10-08T09:41:00+00:00', '2026-10-08T15:12:00+00:00', '2026-10-08T22:37:00+00:00'],
      last_run: {
        at: '2026-10-08T03:50:00+00:00', manual: false, ok: true,
        pairs: [
          { style_id: 80, week_year: 2026, week_number: 38, ok: true, run_id: 'r1', item_count: 300 },
          { style_id: 81, week_year: 2026, week_number: 38, ok: true, run_id: 'r2', item_count: 889 },
          { style_id: 82, week_year: 2026, week_number: 38, ok: true, run_id: 'r3', item_count: 1465 },
        ],
      },
      due_week: { week_year: 2026, week_number: 39 },
      stuck: [],
    }));
    render(
      <Frame qc={qc} width={1720}>
        <Stack gap="lg">
          <CoverageMatrix data={coverage} onCellClick={() => {}} />
          <AutoIngestPanel styleNames={new Map(styles.map((s) => [s.style_id, s.style_name]))} />
        </Stack>
      </Frame>,
    );
    await screen.findByText('Due week: 2026-W39');
    await shoot('coverage');
  });

  test('analytics', async () => {
    const qs = `tz_offset_min=${tzOffsetMin()}`;
    const daily = Array.from({ length: 30 }, (_, i) => {
      const d = new Date(Date.UTC(2026, 8, 9 + i));
      const minutes = 20 + ((i * 47) % 95);
      return { dt: d.toISOString().slice(0, 10), listened_ms: minutes * 60_000, tracks: Math.round(minutes / 3) };
    });
    const qc = client((c) => {
      c.setQueryData(['analytics', 'listening', qs], {
        today: '2026-10-08',
        totals: {
          day: { listened_ms: 52 * 60_000, tracks: 17 },
          week: { listened_ms: 6.4 * 3_600_000, tracks: 131 },
          month: { listened_ms: 31.5 * 3_600_000, tracks: 642 },
        },
        daily,
      });
      c.setQueryData(['analytics', 'funnel', qs], {
        today: '2026-10-08',
        stages: [
          { stage: 'triaged', day: 140, week: 912, month: 3810 },
          { stage: 'categorized', day: 31, week: 206, month: 874 },
          { stage: 'playlisted', day: 9, week: 64, month: 251 },
        ],
      });
      c.setQueryData(['analytics', 'time-per-track', `${qs}&days=30`], {
        days: 30,
        stages: ['triage', 'category', 'playlist'],
        rows: [
          { style_id: '*', style_name: null, cells: {
            triage: { n: 3810, p50_ms: 9_000, p90_ms: 31_000 },
            category: { n: 874, p50_ms: 42_000, p90_ms: 118_000 },
            playlist: { n: 251, p50_ms: 63_000, p90_ms: 171_000 } } },
          { style_id: '81', style_name: 'Funky House', cells: {
            triage: { n: 1420, p50_ms: 8_000, p90_ms: 27_000 },
            category: { n: 330, p50_ms: 39_000, p90_ms: 104_000 },
            playlist: { n: 97, p50_ms: 58_000, p90_ms: 160_000 } } },
          { style_id: '96', style_name: 'Mainstage', cells: {
            triage: { n: 1190, p50_ms: 10_000, p90_ms: 35_000 },
            category: { n: 251, p50_ms: 47_000, p90_ms: 131_000 },
            playlist: { n: 72, p50_ms: 69_000, p90_ms: 182_000 } } },
        ],
      });
    });
    render(
      <Frame qc={qc} width={1392}>
        <SimpleGrid cols={2} spacing="lg">
          <Paper><ListeningCard /></Paper>
          <Paper><FunnelCard /></Paper>
        </SimpleGrid>
        <div style={{ height: 24 }} />
        <TimePerTrackCard />
      </Frame>,
    );
    await screen.findByText('Funky House');
    await shoot('analytics');
  });
});
