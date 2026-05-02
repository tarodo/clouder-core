import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { TracksTab } from '../TracksTab';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </MantineProvider>
  );
}

function mkTracks(start: number, count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: `t${start + i}`,
    title: `Track ${start + i}`,
    mix_name: null,
    artists: [{ id: 'a1', name: 'Artist' }],
    bpm: 120,
    length_ms: 360000,
    publish_date: '2026-01-01',
    isrc: null,
    spotify_id: null,
    release_type: null,
    is_ai_suspected: false,
    added_at: '2026-01-01T00:00:00Z',
    source_triage_block_id: null,
  }));
}

describe('TracksTab', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('renders first page + load-more', async () => {
    server.use(
      http.get('http://localhost/categories/c1/tracks', ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset') ?? '0');
        return HttpResponse.json({
          items: offset === 0 ? mkTracks(0, 50) : mkTracks(50, 10),
          total: 60,
          limit: 50,
          offset,
        });
      }),
    );
    render(
      <Wrapper>
        <TracksTab categoryId="c1" />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Track 0')).toBeInTheDocument());
    expect(screen.getByText(/Show more \(10 remaining\)/i)).toBeInTheDocument();
    await userEvent.click(screen.getByText(/Show more/i));
    await waitFor(() => expect(screen.getByText('Track 50')).toBeInTheDocument());
    expect(screen.queryByText(/Show more/i)).not.toBeInTheDocument();
  });

  it('shows empty-search state', async () => {
    server.use(
      http.get('http://localhost/categories/c1/tracks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <TracksTab categoryId="c1" />
      </Wrapper>,
    );
    await userEvent.type(screen.getByPlaceholderText(/search by title/i), 'zzz');
    await waitFor(() => expect(screen.getByText(/no tracks match 'zzz'/i)).toBeInTheDocument());
  });

  it('shows no-tracks empty state', async () => {
    server.use(
      http.get('http://localhost/categories/c1/tracks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <TracksTab categoryId="c1" />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText(/no tracks yet/i)).toBeInTheDocument());
  });
});
