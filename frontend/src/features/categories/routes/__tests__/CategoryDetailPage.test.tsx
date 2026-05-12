import React from 'react';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications, notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { CategoryDetailPage } from '../CategoryDetailPage';
import { testTheme } from '../../../../test/theme';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(
    [{ path: '/categories/:styleId/:id', element: children }],
    { initialEntries: ['/categories/s1/c1'] },
  );
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <ModalsProvider>
          <Notifications position="top-right" />
          <RouterProvider router={router} />
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>
  );
}

afterEach(() => notifications.clean());

beforeEach(() => {
  tokenStore.set('TOK');
  notifications.clean();
  server.use(
    http.get('http://localhost/categories/c1', () =>
      HttpResponse.json({
        id: 'c1',
        style_id: 's1',
        style_name: 'House',
        name: 'Deep',
        position: 0,
        track_count: 0,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
    http.get('http://localhost/categories/c1/tracks', () =>
      HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
    ),
    http.get('http://localhost/styles/s1/categories', () =>
      HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
    ),
  );
});

describe('CategoryDetailPage', () => {
  it('renders header and empty tracks state', async () => {
    render(
      <Wrapper>
        <CategoryDetailPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Deep')).toBeInTheDocument());
    expect(screen.getByText(/no tracks yet/i)).toBeInTheDocument();
  });

  it('shows not-found on 404', async () => {
    server.use(
      http.get('http://localhost/categories/c1', () =>
        HttpResponse.json(
          { error_code: 'category_not_found', message: 'gone', correlation_id: 'c' },
          { status: 404 },
        ),
      ),
    );
    render(
      <Wrapper>
        <CategoryDetailPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText(/not found/i)).toBeInTheDocument());
  });

  function trackPayload(items: Array<{ id: string; title: string }>) {
    return {
      items: items.map((tr) => ({
        id: tr.id,
        title: tr.title,
        mix_name: null,
        artists: [],
        label: null,
        bpm: null,
        length_ms: null,
        publish_date: null,
        spotify_release_date: null,
        isrc: null,
        spotify_id: null,
        release_type: null,
        is_ai_suspected: false,
        added_at: '2026-01-01T00:00:00Z',
        source_triage_block_id: null,
        tags: [],
      })),
      total: items.length,
      limit: 50,
      offset: 0,
    };
  }

  function styleCategoriesPayload(items: Array<{ id: string; name: string; position: number }>) {
    return {
      items: items.map((c) => ({
        id: c.id,
        style_id: 's1',
        style_name: 'House',
        name: c.name,
        position: c.position,
        track_count: 0,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      })),
      total: items.length,
      limit: 200,
      offset: 0,
    };
  }

  it('move flow: kebab → pick destination → success toast', async () => {
    let postHit = false;
    let deleteHit = false;
    server.use(
      http.get('http://localhost/categories/c1/tracks', () =>
        HttpResponse.json(trackPayload([{ id: 't1', title: 'Lift Off' }])),
      ),
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json(
          styleCategoriesPayload([
            { id: 'c1', name: 'Energetic', position: 0 },
            { id: 'c2', name: 'Deep', position: 1 },
          ]),
        ),
      ),
      http.post('http://localhost/categories/c2/tracks', () => {
        postHit = true;
        return HttpResponse.json({ ok: true });
      }),
      http.delete('http://localhost/categories/c1/tracks/t1', () => {
        deleteHit = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(
      <Wrapper>
        <CategoryDetailPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Lift Off')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /Track actions/i }));
    const menu = await screen.findByRole('menu');
    await userEvent.click(within(menu).getByRole('menuitem', { name: /Move to/ }));
    await userEvent.click(within(menu).getByRole('menuitem', { name: /Deep/ }));

    await waitFor(() => expect(postHit).toBe(true));
    await waitFor(() => expect(deleteHit).toBe(true));
    expect(await screen.findByText(/Moved to Deep/)).toBeInTheDocument();
  });

  it('undo flow: clicking Undo on the move toast posts back and deletes from target', async () => {
    const calls: string[] = [];
    server.use(
      http.get('http://localhost/categories/c1/tracks', () =>
        HttpResponse.json(trackPayload([{ id: 't1', title: 'Lift Off' }])),
      ),
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json(
          styleCategoriesPayload([
            { id: 'c1', name: 'Energetic', position: 0 },
            { id: 'c2', name: 'Deep', position: 1 },
          ]),
        ),
      ),
      http.post('http://localhost/categories/c2/tracks', async ({ request }) => {
        calls.push(`POST c2 ${(await request.json() as { track_id: string }).track_id}`);
        return HttpResponse.json({ ok: true });
      }),
      http.delete('http://localhost/categories/c1/tracks/t1', () => {
        calls.push('DELETE c1');
        return new HttpResponse(null, { status: 204 });
      }),
      http.post('http://localhost/categories/c1/tracks', async ({ request }) => {
        calls.push(`POST c1 ${(await request.json() as { track_id: string }).track_id}`);
        return HttpResponse.json({ ok: true });
      }),
      http.delete('http://localhost/categories/c2/tracks/t1', () => {
        calls.push('DELETE c2');
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(
      <Wrapper>
        <CategoryDetailPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Lift Off')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /Track actions/i }));
    const menu = await screen.findByRole('menu');
    await userEvent.click(within(menu).getByRole('menuitem', { name: /Move to/ }));
    await userEvent.click(within(menu).getByRole('menuitem', { name: /Deep/ }));
    expect(await screen.findByText(/Moved to Deep/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Undo/ }));
    await waitFor(() =>
      expect(calls).toEqual([
        'POST c2 t1',
        'DELETE c1',
        'POST c1 t1',
        'DELETE c2',
      ]),
    );
    expect(await screen.findByText(/Undone/)).toBeInTheDocument();
  });

  it('partial-fail: POST ok + DELETE 500 → toast "in both" with Retry that succeeds', async () => {
    let deleteAttempts = 0;
    server.use(
      http.get('http://localhost/categories/c1/tracks', () =>
        HttpResponse.json(trackPayload([{ id: 't1', title: 'Lift Off' }])),
      ),
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json(
          styleCategoriesPayload([
            { id: 'c1', name: 'Energetic', position: 0 },
            { id: 'c2', name: 'Deep', position: 1 },
          ]),
        ),
      ),
      http.post('http://localhost/categories/c2/tracks', () => HttpResponse.json({ ok: true })),
      http.delete('http://localhost/categories/c1/tracks/t1', () => {
        deleteAttempts += 1;
        if (deleteAttempts === 1) return new HttpResponse(null, { status: 500 });
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(
      <Wrapper>
        <CategoryDetailPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Lift Off')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /Track actions/i }));
    const menu = await screen.findByRole('menu');
    await userEvent.click(within(menu).getByRole('menuitem', { name: /Move to/ }));
    await userEvent.click(within(menu).getByRole('menuitem', { name: /Deep/ }));
    expect(await screen.findByText(/Track is in both categories/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Retry/ }));
    expect(await screen.findByText(/Removed from category/)).toBeInTheDocument();
    expect(deleteAttempts).toBe(2);
  });
});
