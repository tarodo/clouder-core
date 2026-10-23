import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { server } from '../../../../test/setup';
import { AudioProfileStatus } from '../AudioProfileStatus';
import type { components } from '../../../../api/schema';

type Status = components['schemas']['AnalysisStatus'];

function status(over: Partial<Status> = {}): Status {
  return {
    last_claim_at: null,
    last_result_at: null,
    analyzers: [],
    pair: { high: 0, medium: 0, low: 0, clean: 0 },
    queue: { waiting: 0, analyzed: 0, failed: 0, unusable: 0 },
    profile: { waiting: 1200, profiled: 340, failed: 7, unusable: 2 },
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
        <AudioProfileStatus />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const item = (label: string) => screen.getByText(label).parentElement;

describe('AudioProfileStatus', () => {
  it('shows the four queue stats and no models', async () => {
    renderWith(status());
    expect(await screen.findByText('Audio profile')).toBeInTheDocument();
    expect(item('Waiting')).toHaveTextContent('1,200');
    expect(item('Profiled')).toHaveTextContent('340');
    expect(item('Unavailable')).toHaveTextContent('7');
    expect(item('No usable audio')).toHaveTextContent('2');
    expect(screen.getByText('No models yet')).toBeInTheDocument();
  });

  it('shows the model count and the last retrain', async () => {
    renderWith(
      status({ models: { count: 3, last_trained_at: new Date(Date.now() - 2 * 86_400_000).toISOString() } }),
    );
    expect(await screen.findByText(/^Models: 3 · last retrain .*ago$/)).toBeInTheDocument();
  });
});
