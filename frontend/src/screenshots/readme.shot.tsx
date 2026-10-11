/**
 * README screenshots: the app's real components rendered with sample data.
 * Run from frontend/: `pnpm screenshots` → docs/assets/*.png.
 * The live app sits behind a Spotify allow-list, so this is how the README shows it.
 */
import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { page } from 'vitest/browser';
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
import { AutoIngestPanel } from '../features/admin/components/AutoIngestPanel';
import { AUTO_INGEST_KEY } from '../features/admin/hooks/useAutoIngest';
import { FunnelCard, ListeningCard, TimePerTrackCard, fmtMinutes } from '../features/analytics/components/AnalyticsCards';
import { tzOffsetMin } from '../features/analytics/hooks/useAnalytics';
import {
  sampleAutoIngest,
  sampleCoverage,
  sampleFunnel,
  sampleListening,
  sampleTimePerTrack,
} from '../demo/samples';

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
    const coverage = sampleCoverage();
    const styles = coverage.styles;
    const qc = client((c) => c.setQueryData(AUTO_INGEST_KEY, sampleAutoIngest()));
    render(
      <Frame qc={qc} width={1720}>
        <Stack gap="lg">
          <CoverageMatrix data={coverage} onCellClick={() => {}} />
          <AutoIngestPanel styleNames={new Map(styles.map((s) => [s.style_id, s.style_name]))} />
        </Stack>
      </Frame>,
    );
    await screen.findByText('Due week: 2026-W39');
    // Pinned locale/timezone: the 09:41 UTC run reads as such on any machine.
    expect(screen.getByText('10/8/2026, 9:41:00 AM')).toBeTruthy();
    await shoot('coverage');
  });

  test('analytics', async () => {
    const qs = `tz_offset_min=${tzOffsetMin()}`;
    const qc = client((c) => {
      c.setQueryData(['analytics', 'listening', qs], sampleListening());
      c.setQueryData(['analytics', 'funnel', qs], sampleFunnel());
      c.setQueryData(['analytics', 'time-per-track', `${qs}&days=30`], sampleTimePerTrack(30));
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
    // Headline totals agree with the bars.
    const month = sampleListening().daily.reduce((sum, d) => sum + d.listened_ms, 0);
    expect(screen.getByText(fmtMinutes(month))).toBeTruthy();
    await shoot('analytics');
  });
});
