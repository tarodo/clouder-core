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
// matches are the base of both stages after the search. The analyzer profiles the tracks it
// already checked for AI, so AI has been quiet for hours while profiles keep coming.
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
      last_result_at: hoursAgo(5),
    },
    {
      name: 'ai_detect',
      due: 0,
      leased: 0,
      ok: 900,
      ai_detected: 300,
      failed: 0,
      unusable_source: 0,
      last_result_at: hoursAgo(200),
    },
    {
      name: 'ai_lofcz',
      due: 0,
      leased: 0,
      ok: 26746,
      ai_detected: 5629,
      failed: 133,
      unusable_source: 30,
      last_result_at: hoursAgo(5),
    },
    {
      name: 'light_profile',
      due: 66819,
      leased: 20,
      ok: 3927,
      ai_detected: 0,
      failed: 1,
      unusable_source: 0,
      last_result_at: hoursAgo(0.05),
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
  models: { count: 0, last_trained_at: null },
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
    expect(row(sp, 'Waiting')).toHaveTextContent(/^Waiting0$/);
    // a done row is a share of the searched tracks, not of the catalog
    const yt = await stage('YouTube Music');
    expect(row(yt, 'Matched')).toHaveTextContent('Matched70,76791.2%');
    expect(row(yt, 'Needs review')).toHaveTextContent('Needs review2,6843.5%');
    expect(row(yt, 'Not on YT Music')).toHaveTextContent('Not on YT Music4,1335.3%');
    expect(row(yt, 'Error')).toHaveTextContent('Error4<0.1%');
    expect(row(yt, 'Waiting')).toHaveTextContent(/^Waiting144,410$/);
    expect(yt).toHaveTextContent('19,667 with a comments video');
    expect(yt).toHaveTextContent('250 searched in the last 10 min');
  });

  it('splits the AI stage into the badge levels, clean and the queue', async () => {
    renderWith();
    const ai = await stage('AI detection');
    for (const [label, text, level] of [
      ['Both detectors', 'AIBoth detectors5,39520.0%', 'high'],
      ['lofcz only', 'AIlofcz only2340.9%', 'medium'],
      ['Deezer only', 'AIDeezer only3101.2%', 'low'],
    ] as const) {
      expect(row(ai, label)).toHaveTextContent(text);
      expect(row(ai, label)?.querySelector('[data-level]')).toHaveAttribute('data-level', level);
    }
    // shares of the 26,918 checked tracks
    expect(row(ai, 'Clean')).toHaveTextContent('Clean20,81677.3%');
    expect(row(ai, 'Unavailable')).toHaveTextContent('Unavailable1330.5%');
    expect(row(ai, 'No usable audio')).toHaveTextContent('No usable audio300.1%');
    expect(row(ai, 'In progress')).toHaveTextContent(/^In progress0$/);
    expect(row(ai, 'Waiting')).toHaveTextContent(/^Waiting43,849$/);
  });

  it('sums up the AI verdicts and each detector, never ArtifactNet', async () => {
    renderWith();
    const ai = await stage('AI detection');
    expect(ai).toHaveTextContent('Any AI: 5,939 · 22.1% of checked');
    expect(ai).toHaveTextContent('lofcz: 5,629 AI · 21,117 clean');
    expect(ai).toHaveTextContent('Deezer: 5,705 AI · 21,078 clean');
    expect(ai).not.toHaveTextContent(/ai_detect|ArtifactNet/);
  });

  it('badges each analysis stage by its own last result', async () => {
    renderWith();
    const badge = (el: HTMLElement) => el.querySelector('[data-tone]');
    // AI waits for the profile backfill: quiet for 5 hours (ArtifactNet's 200 do not count)
    const ai = await stage('AI detection');
    expect(badge(ai)).toHaveTextContent('Idle');
    expect(badge(ai)).toHaveAttribute('data-tone', 'gray');
    expect(ai).toHaveTextContent('Last result 5 hours ago');
    const profile = await stage('Audio profile');
    expect(badge(profile)).toHaveTextContent('Running');
    expect(badge(profile)).toHaveAttribute('data-tone', 'green');
    expect(profile).toHaveTextContent(/Last result .*minutes? ago/);
  });

  it('splits the audio profile and shows the models', async () => {
    renderWith({
      analysis: analysis({ models: { count: 3, last_trained_at: hoursAgo(30) } }),
    });
    const profile = await stage('Audio profile');
    expect(row(profile, 'Profiled')).toHaveTextContent('Profiled3,927100.0%');
    expect(row(profile, 'Unavailable')).toHaveTextContent('Unavailable1<0.1%');
    expect(row(profile, 'In progress')).toHaveTextContent(/^In progress20$/);
    expect(row(profile, 'Waiting')).toHaveTextContent(/^Waiting66,819$/);
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

  it('warns on both analysis stages when the analyzer has not called in for days', async () => {
    renderWith({ analysis: analysis({ last_claim_at: hoursAgo(4 * 24 + 1) }) });
    expect(await screen.findAllByText('No run for 4 days')).toHaveLength(2);
  });

  it('says so when the analyzer never ran', async () => {
    renderWith({
      analysis: analysis({ last_claim_at: null, last_result_at: null, analyzers: [] }),
    });
    expect(await screen.findAllByText('Never ran')).toHaveLength(2);
    expect(screen.queryByText(/^Last result|No results yet/)).toBeNull();
    expect(screen.queryByText(/^lofcz:|^Deezer:/)).toBeNull();
  });

  it('says when a stage has no result yet', async () => {
    const quiet = analysis().analyzers.map((a) =>
      a.name === 'light_profile' ? { ...a, last_result_at: null } : a,
    );
    renderWith({ analysis: analysis({ analyzers: quiet }) });
    const profile = await stage('Audio profile');
    expect(profile.querySelector('[data-tone]')).toHaveTextContent('Idle');
    expect(profile).toHaveTextContent('No results yet');
    expect(await stage('AI detection')).toHaveTextContent('Last result 5 hours ago');
  });
});
