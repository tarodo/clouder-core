import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import '../../../../i18n';
import { BucketTracksList } from '../BucketTracksList';
import type { TriageBucket } from '../../lib/bucketLabels';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MantineProvider>{children}</MantineProvider>
    </QueryClientProvider>
  );
}

const buckets: TriageBucket[] = [
  { id: 'bk', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 2 },
  { id: 'dst', bucket_type: 'OLD', category_id: null, category_name: null, inactive: false, track_count: 0 },
];

function mkTracks(ids: string[], total: number) {
  return {
    items: ids.map((id) => ({
      track_id: id,
      title: `Track ${id}`,
      mix_name: null,
      isrc: null,
      bpm: 124,
      length_ms: 360_000,
      publish_date: null,
      spotify_release_date: null,
      spotify_id: null,
      release_type: null,
      is_ai_suspected: false,
      artists: [],
      added_at: '2026-04-21T08:00:00Z',
    })),
    total,
    limit: 50,
    offset: 0,
  };
}

describe('BucketTracksList', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('renders empty state with default body for non-UNCLASSIFIED bucket', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk/tracks', () =>
        HttpResponse.json(mkTracks([], 0)),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    render(
      <BucketTracksList
        blockId="b1"
        bucket={buckets[0]!}
        buckets={buckets}
        showMoveMenu
        onMove={vi.fn()}
      />,
      { wrapper: wrap(qc) },
    );
    expect(await screen.findByText(/No tracks in this bucket/)).toBeInTheDocument();
    expect(screen.getByText(/Move tracks here from another bucket/)).toBeInTheDocument();
  });

  it('renders UNCLASSIFIED-specific empty body', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk/tracks', () =>
        HttpResponse.json(mkTracks([], 0)),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    render(
      <BucketTracksList
        blockId="b1"
        bucket={{ ...buckets[0]!, bucket_type: 'UNCLASSIFIED' }}
        buckets={buckets}
        showMoveMenu
        onMove={vi.fn()}
      />,
      { wrapper: wrap(qc) },
    );
    expect(await screen.findByText(/Spotify release date is missing/)).toBeInTheDocument();
  });

  it('debounces search and includes search param', async () => {
    let lastUrl = '';
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk/tracks', ({ request }) => {
        lastUrl = request.url;
        return HttpResponse.json(mkTracks([], 0));
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    render(
      <BucketTracksList
        blockId="b1"
        bucket={buckets[0]!}
        buckets={buckets}
        showMoveMenu
        onMove={vi.fn()}
      />,
      { wrapper: wrap(qc) },
    );
    await screen.findByText(/No tracks in this bucket/);
    await userEvent.type(screen.getByPlaceholderText(/Search tracks/), 'foo');
    await waitFor(() => expect(lastUrl).toContain('search=foo'), { timeout: 1500 });
  });

  it('renders rows + load-more', async () => {
    let calls = 0;
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk/tracks', ({ request }) => {
        calls += 1;
        const url = new URL(request.url);
        const offset = Number(url.searchParams.get('offset') ?? '0');
        if (offset === 0) return HttpResponse.json({ ...mkTracks(['t1'], 2), limit: 1 });
        return HttpResponse.json({ ...mkTracks(['t2'], 2), limit: 1, offset: 1 });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    render(
      <BucketTracksList
        blockId="b1"
        bucket={buckets[0]!}
        buckets={buckets}
        showMoveMenu
        onMove={vi.fn()}
      />,
      { wrapper: wrap(qc) },
    );
    await screen.findByText('Track t1');
    expect(screen.queryByText('Track t2')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Load more/ }));
    await screen.findByText('Track t2');
    expect(calls).toBe(2);
  });

  it('hides MoveToMenu rows when showMoveMenu=false', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk/tracks', () =>
        HttpResponse.json(mkTracks(['t1'], 1)),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    render(
      <BucketTracksList
        blockId="b1"
        bucket={buckets[0]!}
        buckets={buckets}
        showMoveMenu={false}
        onMove={vi.fn()}
      />,
      { wrapper: wrap(qc) },
    );
    await screen.findByText('Track t1');
    expect(screen.queryByRole('button', { name: /Move track/ })).not.toBeInTheDocument();
  });
});
