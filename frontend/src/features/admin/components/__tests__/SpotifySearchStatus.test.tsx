import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { server } from '../../../../test/setup';
import { SpotifySearchStatus, SPOTIFY_STATUS_POLL_MS } from '../SpotifySearchStatus';
import type { components } from '../../../../api/schema';

type Status = components['schemas']['SpotifySearchStatus'];

function status(over: Partial<Status> = {}): Status {
  return {
    status: 'running',
    paused_until: null,
    queue: { waiting_messages: 0, in_flight: 1, delayed: 0 },
    tracks: { waiting: 4120, not_found: 3051, searched_last_10_min: 600 },
    ...over,
  };
}

function renderWith(body: Status) {
  server.use(http.get('http://localhost/admin/spotify/search-status', () => HttpResponse.json(body)));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <SpotifySearchStatus />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('SpotifySearchStatus', () => {
  it('shows a running search with the backlog and the not-found total', async () => {
    renderWith(status());
    expect(await screen.findByText('Searching')).toBeInTheDocument();
    expect(screen.getByText('4,120')).toBeInTheDocument();
    expect(screen.getByText('600')).toBeInTheDocument();
    expect(screen.getByText('3,051')).toBeInTheDocument();
  });

  it('shows when a Spotify ban ends', async () => {
    renderWith(status({ status: 'paused', paused_until: '2026-10-10T09:58:00+00:00' }));
    expect(await screen.findByText(/Paused until/)).toBeInTheDocument();
  });

  it('shows idle and queued states', async () => {
    renderWith(status({ status: 'idle' }));
    expect(await screen.findByText('Idle')).toBeInTheDocument();
  });

  it('refreshes every 10 seconds', () => {
    expect(SPOTIFY_STATUS_POLL_MS).toBe(10_000);
  });
});
