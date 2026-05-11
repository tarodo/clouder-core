import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { MemoryRouter } from 'react-router';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { TracksTab } from '../TracksTab';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>
  );
}

function RouterWrapper({
  initialUrl,
  children,
}: {
  initialUrl: string;
  children: React.ReactNode;
}) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  return (
    <MantineProvider theme={testTheme}>
      <ModalsProvider>
        <Notifications />
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={[initialUrl]}>{children}</MemoryRouter>
        </QueryClientProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

function mkTracks(start: number, count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: `t${start + i}`,
    title: `Track ${start + i}`,
    mix_name: null,
    artists: [{ id: 'a1', name: 'Artist' }],
    label: { id: 'l1', name: 'Cool Label' },
    bpm: 120,
    length_ms: 360000,
    publish_date: '2026-01-01',
    spotify_release_date: '2026-01-03',
    isrc: null,
    spotify_id: null,
    release_type: null,
    is_ai_suspected: false,
    added_at: '2026-01-01T00:00:00Z',
    source_triage_block_id: null,
    tags: [],
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
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <TracksTab categoryId="c1" styleId="s1" />
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
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <TracksTab categoryId="c1" styleId="s1" />
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
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <TracksTab categoryId="c1" styleId="s1" />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText(/no tracks yet/i)).toBeInTheDocument());
  });

  it('renders Title and Released sortable headers with default sort', async () => {
    server.use(
      http.get('http://localhost/categories/c1/tracks', () =>
        HttpResponse.json({ items: mkTracks(0, 1), total: 1, limit: 50, offset: 0 }),
      ),
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <TracksTab categoryId="c1" styleId="s1" />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Track 0')).toBeInTheDocument());
    expect(
      screen.getByRole('columnheader', { name: /Added/i }),
    ).toHaveAttribute('aria-sort', 'descending');
    expect(
      screen.getByRole('columnheader', { name: /Title/i }),
    ).toHaveAttribute('aria-sort', 'none');
  });

  it('clicking Title switches sort to title asc, then desc', async () => {
    let lastSort = '';
    let lastOrder = '';
    server.use(
      http.get('http://localhost/categories/c1/tracks', ({ request }) => {
        const url = new URL(request.url);
        lastSort = url.searchParams.get('sort') ?? '';
        lastOrder = url.searchParams.get('order') ?? '';
        return HttpResponse.json({
          items: mkTracks(0, 1),
          total: 1,
          limit: 50,
          offset: 0,
        });
      }),
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <TracksTab categoryId="c1" styleId="s1" />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Track 0')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /Title/i }));
    await waitFor(() => expect(lastSort).toBe('title'));
    expect(lastOrder).toBe('asc');
    await userEvent.click(screen.getByRole('button', { name: /Title/i }));
    await waitFor(() => expect(lastOrder).toBe('desc'));
    expect(lastSort).toBe('title');
  });

  it('renders an actions column with a kebab trigger per row (desktop)', async () => {
    server.use(
      http.get('http://localhost/categories/c1/tracks', () =>
        HttpResponse.json({ items: mkTracks(0, 2), total: 2, limit: 50, offset: 0 }),
      ),
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <TracksTab categoryId="c1" styleId="s1" />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Track 0')).toBeInTheDocument());
    expect(screen.getAllByRole('button', { name: /Track actions/i })).toHaveLength(2);
  });

  it('forwards tag filter from URL into useCategoryTracks request', async () => {
    let captured: URL | null = null;
    server.use(
      http.get('http://localhost/tags', () =>
        HttpResponse.json({
          items: [{ id: 'tg1', name: 'Vocal', color: '#ff8800',
                    created_at: 'x', updated_at: 'x' }],
          total: 1, limit: 200, offset: 0,
        }),
      ),
      http.get('http://localhost/categories/c1/tracks', ({ request }) => {
        captured = new URL(request.url);
        return HttpResponse.json({
          items: [], total: 0, limit: 50, offset: 0,
        });
      }),
    );
    render(
      <RouterWrapper initialUrl="/categories/c1?tags=tg1&match=any">
        <TracksTab categoryId="c1" styleId="s1" />
      </RouterWrapper>,
    );
    await waitFor(() => {
      expect(captured?.searchParams.get('tags')).toBe('tg1');
      expect(captured?.searchParams.get('match')).toBe('any');
    });
  });

  it('opens the manage-tags modal when the button is clicked', async () => {
    server.use(
      http.get('http://localhost/tags', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
      http.get('http://localhost/categories/c1/tracks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    render(
      <RouterWrapper initialUrl="/categories/c1">
        <TracksTab categoryId="c1" styleId="s1" />
      </RouterWrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /manage tags/i }));
    expect(await screen.findByRole('dialog', { name: /manage tags/i })).toBeInTheDocument();
  });
});
