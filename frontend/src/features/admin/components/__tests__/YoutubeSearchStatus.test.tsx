import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { server } from '../../../../test/setup';
import { YoutubeSearchStatus } from '../YoutubeSearchStatus';
import type { components } from '../../../../api/schema';

type Status = components['schemas']['YoutubeSearchStatus'];

function status(over: Partial<Status> = {}): Status {
  return {
    status: 'running',
    paused_until: null,
    queue: { waiting_messages: 0, in_flight: 1, delayed: 0 },
    tracks: { waiting: 1250, searched_last_10_min: 210, searched_total: 4600 },
    results: { matched: 3400, needs_review: 940, not_found: 3, videos: 1200 },
    ...over,
  };
}

function renderWith(body: Status) {
  server.use(http.get('http://localhost/admin/youtube/search-status', () => HttpResponse.json(body)));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <YoutubeSearchStatus />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('YoutubeSearchStatus', () => {
  it('shows the backlog and what the search found', async () => {
    renderWith(status());
    expect(await screen.findByText('YouTube search')).toBeInTheDocument();
    expect(screen.getByText('Searching')).toBeInTheDocument();
    expect(screen.getByText('1,250')).toBeInTheDocument(); // waiting
    expect(screen.getByText('210')).toBeInTheDocument(); // last 10 min
    expect(screen.getByText('4,600')).toBeInTheDocument(); // searched
    expect(screen.getByText('3,400')).toBeInTheDocument(); // matched
    expect(screen.getByText('940')).toBeInTheDocument(); // review
    expect(screen.getByText('1,200')).toBeInTheDocument(); // videos
  });

  it('shows when a YouTube pause ends', async () => {
    renderWith(status({ status: 'paused', paused_until: '2026-10-15T09:58:00+00:00' }));
    expect(await screen.findByText(/Paused until/)).toBeInTheDocument();
  });

  it('shows the idle state', async () => {
    renderWith(status({ status: 'idle' }));
    expect(await screen.findByText('Idle')).toBeInTheDocument();
  });
});
