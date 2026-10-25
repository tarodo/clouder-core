import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { server } from '../../../../test/setup';
import { PipelineStatus } from '../PipelineStatus';
import type { components } from '../../../../api/schema';

type Spotify = components['schemas']['SpotifySearchStatus'];
type Youtube = components['schemas']['YoutubeSearchStatus'];
type Analysis = components['schemas']['AnalysisStatus'];

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();
const idleQueue = { waiting_messages: 0, in_flight: 0, delayed: 0 };

// A prod snapshot (2026-10-25): every stage's rows add up to its total, and the YT Music
// matches are the base of both stages after the search.
const spotify = (over: Partial<Spotify> = {}): Spotify => ({
  status: 'idle',
  paused_until: null,
  queue: idleQueue,
  tracks: {
    total: 221998,
    found: 215513,
    not_found: 6485,
    waiting: 0,
    no_isrc: 0,
    searched_last_10_min: 0,
  },
  ...over,
});

const youtube = (over: Partial<Youtube> = {}): Youtube => ({
  status: 'idle',
  paused_until: null,
  queue: idleQueue,
  tracks: { total: 221998, waiting: 144410, searched_last_10_min: 250 },
  results: { matched: 70767, needs_review: 2684, not_found: 4133, error: 4, videos: 19667 },
  ...over,
});

const analysis = (over: Partial<Analysis> = {}): Analysis => ({
  last_claim_at: hoursAgo(0.1),
  last_result_at: hoursAgo(0.2),
  analyzers: [
    {
      name: 'ai_deezer',
      due: 0,
      leased: 0,
      ok: 26783,
      ai_detected: 5705,
      failed: 133,
      unusable_source: 30,
    },
    {
      name: 'ai_detect',
      due: 0,
      leased: 0,
      ok: 900,
      ai_detected: 300,
      failed: 0,
      unusable_source: 0,
    },
    {
      name: 'ai_lofcz',
      due: 0,
      leased: 0,
      ok: 26746,
      ai_detected: 5629,
      failed: 133,
      unusable_source: 30,
    },
  ],
  pair: { high: 5395, medium: 234, low: 310, clean: 20816 },
  queue: { total: 70767, waiting: 43849, in_progress: 0, failed: 133, unusable: 30 },
  profile: {
    total: 70767,
    waiting: 66819,
    in_progress: 20,
    profiled: 3927,
    failed: 1,
    unusable: 0,
  },
  models: { count: 0, last_trained_at: null, items: [] },
  ...over,
});

function renderWith(bodies: { spotify?: Spotify; youtube?: Youtube; analysis?: Analysis } = {}) {
  server.use(
    http.get('http://localhost/admin/spotify/search-status', () =>
      HttpResponse.json(bodies.spotify ?? spotify()),
    ),
    http.get('http://localhost/admin/youtube/search-status', () =>
      HttpResponse.json(bodies.youtube ?? youtube()),
    ),
    http.get('http://localhost/admin/analysis/status', () =>
      HttpResponse.json(bodies.analysis ?? analysis()),
    ),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <PipelineStatus />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

async function stage(title: string): Promise<HTMLElement> {
  await screen.findByText(title);
  const el = document.querySelector<HTMLElement>(`[data-stage="${title}"]`);
  if (!el) throw new Error(`no stage ${title}`);
  return el;
}

const row = (el: HTMLElement, label: string) => el.querySelector(`[data-bucket="${label}"]`);

describe('PipelineStatus', () => {
  it('heads the block with the Beatport catalog', async () => {
    renderWith();
    expect(await screen.findByText('Track pipeline')).toBeInTheDocument();
    expect(await screen.findByText('221,998 Beatport tracks')).toBeInTheDocument();
  });

  it('shows each stage as done of its base', async () => {
    renderWith();
    const yt = await stage('YouTube Music');
    expect(yt).toHaveTextContent('77,588/ 221,998');
    expect(yt).toHaveTextContent('Searched · 34.9% of the Beatport catalog');
    const ai = await stage('AI detection');
    expect(ai).toHaveTextContent('26,918/ 70,767');
    expect(ai).toHaveTextContent('Checked · 38.0% of YT Music matches');
    const profile = await stage('Audio profile');
    expect(profile).toHaveTextContent('3,928/ 70,767');
  });

  it('splits Spotify and YouTube into the catalog buckets', async () => {
    renderWith();
    const sp = await stage('Spotify');
    expect(row(sp, 'Found')).toHaveTextContent('Found215,51397.1%');
    expect(row(sp, 'Not found')).toHaveTextContent('Not found6,4852.9%');
    expect(row(sp, 'No ISRC')).toHaveTextContent('No ISRC00.0%');
    expect(row(sp, 'Waiting')).toHaveTextContent('Waiting00.0%');
    const yt = await stage('YouTube Music');
    expect(row(yt, 'Matched')).toHaveTextContent('Matched70,76731.9%');
    expect(row(yt, 'Needs review')).toHaveTextContent('Needs review2,6841.2%');
    expect(row(yt, 'Not on YT Music')).toHaveTextContent('Not on YT Music4,1331.9%');
    expect(row(yt, 'Error')).toHaveTextContent('Error4<0.1%');
    expect(row(yt, 'Waiting')).toHaveTextContent('Waiting144,41065.1%');
    expect(yt).toHaveTextContent('19,667 with a comments video');
    expect(yt).toHaveTextContent('250 searched in the last 10 min');
  });

  it('splits the AI stage into the badge levels, clean and the queue', async () => {
    renderWith();
    const ai = await stage('AI detection');
    for (const [label, text, level] of [
      ['Both detectors', 'AIBoth detectors5,3957.6%', 'high'],
      ['lofcz only', 'AIlofcz only2340.3%', 'medium'],
      ['Deezer only', 'AIDeezer only3100.4%', 'low'],
    ] as const) {
      expect(row(ai, label)).toHaveTextContent(text);
      expect(row(ai, label)?.querySelector('[data-level]')).toHaveAttribute('data-level', level);
    }
    expect(row(ai, 'Clean')).toHaveTextContent('Clean20,81629.4%');
    expect(row(ai, 'Unavailable')).toHaveTextContent('Unavailable1330.2%');
    expect(row(ai, 'No usable audio')).toHaveTextContent('No usable audio30<0.1%');
    expect(row(ai, 'In progress')).toHaveTextContent('In progress00.0%');
    expect(row(ai, 'Waiting')).toHaveTextContent('Waiting43,84962.0%');
  });

  it('sums up the AI verdicts and each detector, never ArtifactNet', async () => {
    renderWith();
    const ai = await stage('AI detection');
    expect(ai).toHaveTextContent('Any AI: 5,939 · 22.2% of verdicts');
    expect(ai).toHaveTextContent('lofcz: 5,629 AI · 21,117 clean');
    expect(ai).toHaveTextContent('Deezer: 5,705 AI · 21,078 clean');
    expect(ai).not.toHaveTextContent(/ai_detect|ArtifactNet/);
    expect(ai).toHaveTextContent(/Last result .*ago/);
  });

  it('splits the audio profile and shows the models', async () => {
    renderWith({
      analysis: analysis({ models: { count: 3, last_trained_at: hoursAgo(30), items: [] } }),
    });
    const profile = await stage('Audio profile');
    expect(row(profile, 'Profiled')).toHaveTextContent('Profiled3,9275.5%');
    expect(row(profile, 'In progress')).toHaveTextContent('In progress20<0.1%');
    expect(row(profile, 'Waiting')).toHaveTextContent('Waiting66,81994.4%');
    expect(profile).toHaveTextContent(/Models: 3 · last retrain .*ago/);
  });

  it('shows the search states', async () => {
    renderWith({
      spotify: spotify({ status: 'running' }),
      youtube: youtube({
        status: 'paused',
        paused_until: new Date(Date.now() + 3_600_000).toISOString(),
      }),
    });
    expect(await screen.findByText('Searching')).toBeInTheDocument();
    expect(await screen.findByText(/^Paused until/)).toBeInTheDocument();
  });

  it('warns when the analyzer has not called in for days', async () => {
    renderWith({ analysis: analysis({ last_claim_at: hoursAgo(4 * 24 + 1) }) });
    expect(await screen.findByText('No run for 4 days')).toBeInTheDocument();
  });

  it('says so when the analyzer never ran', async () => {
    renderWith({
      analysis: analysis({ last_claim_at: null, last_result_at: null, analyzers: [] }),
    });
    expect(await screen.findByText('Never ran')).toBeInTheDocument();
    expect(screen.queryByText(/^Last result|No results yet/)).toBeNull();
    expect(screen.queryByText(/^lofcz:|^Deezer:/)).toBeNull();
  });

  it('says when the analyzer claims but has not posted a result yet', async () => {
    renderWith({ analysis: analysis({ last_result_at: null }) });
    expect(await screen.findByText('No results yet')).toBeInTheDocument();
  });
});
