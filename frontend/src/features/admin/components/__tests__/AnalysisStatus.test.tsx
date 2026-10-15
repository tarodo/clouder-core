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
    ],
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

describe('AnalysisStatus', () => {
  it('shows the last run and the counts per analyzer', async () => {
    renderWith(status());
    expect(await screen.findByText('AI analysis')).toBeInTheDocument();
    expect(screen.getByText(/^Last run/)).toBeInTheDocument();
    expect(screen.getByText('120')).toBeInTheDocument();
    expect(screen.getByText('3,400')).toBeInTheDocument();
    expect(screen.getByText('41')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
  });

  it('warns when the analyzer has not called in for days', async () => {
    renderWith(status({ last_claim_at: hoursAgo(4 * 24 + 1) }));
    expect(await screen.findByText('No run for 4 days')).toBeInTheDocument();
  });

  it('says so when the analyzer never ran', async () => {
    renderWith(status({ last_claim_at: null, last_result_at: null, analyzers: [] }));
    expect(await screen.findByText('Never ran')).toBeInTheDocument();
  });
});
