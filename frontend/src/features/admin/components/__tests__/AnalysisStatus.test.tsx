import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { server } from '../../../../test/setup';
import { AnalysisStatus } from '../AnalysisStatus';
import type { components } from '../../../../api/schema';

type Status = components['schemas']['AnalysisStatus'];

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();

function status(over: Partial<Status> = {}): Status {
  return {
    last_claim_at: hoursAgo(5),
    last_result_at: hoursAgo(5),
    analyzers: [
      { name: 'ai_detect', due: 120, leased: 0, ok: 3400, ai_detected: 41, failed: 12, unusable_source: 3 },
      { name: 'ai_lofcz', due: 7, leased: 0, ok: 900, ai_detected: 8, failed: 6, unusable_source: 2 },
    ],
    pair: { high: 3745, medium: 151, low: 224, clean: 14952 },
    queue: { waiting: 41633, analyzed: 19072, failed: 82, unusable: 25 },
    profile: { waiting: 120, profiled: 800, failed: 5, unusable: 2 },
    models: { count: 0, last_trained_at: null },
    ...over,
  };
}

function renderWith(body: Status) {
  server.use(http.get('http://localhost/admin/analysis/status', () => HttpResponse.json(body)));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <AnalysisStatus />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

// The label and its number sit side by side in one item.
const item = (label: string) => screen.getByText(label).parentElement;

describe('AnalysisStatus', () => {
  it('shows the last run and the last result', async () => {
    renderWith(status());
    expect(await screen.findByText('AI analysis')).toBeInTheDocument();
    expect(screen.getByText(/^Last run .*ago$/)).toBeInTheDocument();
    expect(screen.getByText(/^Last result .*ago$/)).toBeInTheDocument();
  });

  it('shows the pair levels with the track badge colors, and the clean count', async () => {
    renderWith(status());
    await screen.findByText('AI analysis');
    for (const [label, value, level] of [
      ['Both detectors', '3,745', 'high'],
      ['lofcz only', '151', 'medium'],
      ['Deezer only', '224', 'low'],
    ] as const) {
      expect(item(label)).toHaveTextContent(`AI${label}${value}`);
      expect(item(label)?.querySelector('[data-level]')).toHaveAttribute('data-level', level);
    }
    expect(item('Clean')).toHaveTextContent('Clean14,952');
  });

  it("shows the pair's queue", async () => {
    renderWith(status());
    expect(await screen.findByText('Queue:')).toBeInTheDocument();
    expect(item('Waiting')).toHaveTextContent('Waiting41,633');
    expect(item('Analyzed')).toHaveTextContent('Analyzed19,072');
    expect(item('Unavailable')).toHaveTextContent('Unavailable82');
    expect(item('No usable audio')).toHaveTextContent('No usable audio25');
  });

  it('shows no per-analyzer blocks', async () => {
    const { container } = renderWith(status());
    await screen.findByText('AI analysis');
    expect(container).not.toHaveTextContent(/ai_detect|ai_lofcz|AI detected/);
    for (const n of ['120', '3,400', '41', '12']) expect(screen.queryByText(n)).toBeNull();
  });

  it('warns when the analyzer has not called in for days', async () => {
    renderWith(status({ last_claim_at: hoursAgo(4 * 24 + 1) }));
    expect(await screen.findByText('No run for 4 days')).toBeInTheDocument();
  });

  it('says so when the analyzer never ran', async () => {
    renderWith(status({ last_claim_at: null, last_result_at: null, analyzers: [] }));
    expect(await screen.findByText('Never ran')).toBeInTheDocument();
    expect(screen.queryByText(/^Last result|No results yet/)).toBeNull();
  });

  it('says when the analyzer claims but has not posted a result yet', async () => {
    renderWith(status({ last_result_at: null }));
    expect(await screen.findByText('No results yet')).toBeInTheDocument();
  });
});
