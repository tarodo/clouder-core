import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications, notifications } from '@mantine/notifications';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/setup';
import { tokenStore } from '../../../auth/tokenStore';
import '../../../i18n';
import { BucketDetailPage } from '../routes/BucketDetailPage';

function renderAt(path: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: '/triage/:styleId/:id/buckets/:bucketId', element: <BucketDetailPage /> },
      { path: '/triage/:styleId/:id', element: <div data-testid="block-page" /> },
      { path: '/triage/:styleId', element: <div data-testid="list-page" /> },
    ],
    { initialEntries: [path] },
  );
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <ModalsProvider>
          <Notifications position="top-right" />
          <RouterProvider router={router} />
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const inProgressBlock = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'W17',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS',
  created_at: '2026-04-21T08:00:00Z',
  updated_at: '2026-04-21T08:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'bk1', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 2 },
    { id: 'bk2', bucket_type: 'OLD', category_id: null, category_name: null, inactive: false, track_count: 0 },
    { id: 'bk3', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Tech', inactive: false, track_count: 0 },
  ],
};

function track(id: string) {
  return {
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
  };
}

describe('BucketDetailPage integration', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    notifications.clean();
  });
  afterEach(() => notifications.clean());

  it('renders track list and load-more', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', ({ request }) => {
        const url = new URL(request.url);
        const offset = Number(url.searchParams.get('offset') ?? '0');
        if (offset === 0) {
          return HttpResponse.json({ items: [track('t1')], total: 2, limit: 1, offset: 0 });
        }
        return HttpResponse.json({ items: [track('t2')], total: 2, limit: 1, offset: 1 });
      }),
    );
    renderAt('/triage/s1/b1/buckets/bk1');
    await screen.findByText('Track t1');
    expect(screen.queryByText('Track t2')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Load more/ }));
    await screen.findByText('Track t2');
  });

  it('move happy path: row disappears + green toast with Undo', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', () =>
        HttpResponse.json({ items: [track('t1'), track('t2')], total: 2, limit: 50, offset: 0 }),
      ),
      http.get('http://localhost/triage/blocks/b1/buckets/bk2/tracks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
      http.post('http://localhost/triage/blocks/b1/move', () =>
        HttpResponse.json({ moved: 1 }),
      ),
    );
    renderAt('/triage/s1/b1/buckets/bk1');
    await screen.findByText('Track t1');
    const triggers = await screen.findAllByRole('button', { name: /Move track/ });
    await userEvent.click(triggers[0]!);
    await userEvent.click(await screen.findByRole('menuitem', { name: /Move to OLD/ }));
    // Optimistic — t1 should disappear from the list
    await waitFor(() => expect(screen.queryByText('Track t1')).not.toBeInTheDocument());
    // Toast
    expect(await screen.findByText(/Moved 1 track/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Undo/ })).toBeInTheDocument();
  });

  it('Undo within 5s puts the track back', async () => {
    let postCount = 0;
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', () =>
        HttpResponse.json({ items: [track('t1'), track('t2')], total: 2, limit: 50, offset: 0 }),
      ),
      http.get('http://localhost/triage/blocks/b1/buckets/bk2/tracks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
      http.post('http://localhost/triage/blocks/b1/move', () => {
        postCount += 1;
        return HttpResponse.json({ moved: 1 });
      }),
    );
    renderAt('/triage/s1/b1/buckets/bk1');
    await screen.findByText('Track t1');
    const triggers = await screen.findAllByRole('button', { name: /Move track/ });
    await userEvent.click(triggers[0]!);
    await userEvent.click(await screen.findByRole('menuitem', { name: /Move to OLD/ }));
    const undoBtn = await screen.findByRole('button', { name: /Undo/ });
    await userEvent.click(undoBtn);
    await waitFor(() => expect(screen.getByText('Track t1')).toBeInTheDocument());
    await waitFor(() => expect(postCount).toBe(2));
    expect(await screen.findByText(/Undone/)).toBeInTheDocument();
  });

  it('move 409 target_bucket_inactive: rollback + red toast', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', () =>
        HttpResponse.json({ items: [track('t1')], total: 1, limit: 50, offset: 0 }),
      ),
      http.post('http://localhost/triage/blocks/b1/move', () =>
        HttpResponse.json(
          { error_code: 'target_bucket_inactive', message: 'no' },
          { status: 409 },
        ),
      ),
    );
    renderAt('/triage/s1/b1/buckets/bk1');
    await screen.findByText('Track t1');
    const trigger = await screen.findByRole('button', { name: /Move track/ });
    await userEvent.click(trigger);
    await userEvent.click(await screen.findByRole('menuitem', { name: /Move to OLD/ }));
    expect(await screen.findByText(/destination is no longer valid/i)).toBeInTheDocument();
    // Track restored
    expect(screen.getByText('Track t1')).toBeInTheDocument();
  });

  it('FINALIZED block: no MoveMenu', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () =>
        HttpResponse.json({
          ...inProgressBlock,
          status: 'FINALIZED',
          finalized_at: '2026-04-22T00:00:00Z',
        }),
      ),
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', () =>
        HttpResponse.json({ items: [track('t1')], total: 1, limit: 50, offset: 0 }),
      ),
    );
    renderAt('/triage/s1/b1/buckets/bk1');
    await screen.findByText('Track t1');
    expect(screen.queryByRole('button', { name: /Move track/ })).not.toBeInTheDocument();
  });

  it('search miss empty state with clear-search action', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', ({ request }) => {
        const url = new URL(request.url);
        const search = url.searchParams.get('search');
        if (search === 'xyz') {
          return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
        }
        return HttpResponse.json({ items: [track('t1')], total: 1, limit: 50, offset: 0 });
      }),
    );
    renderAt('/triage/s1/b1/buckets/bk1');
    await screen.findByText('Track t1');
    await userEvent.type(screen.getByPlaceholderText(/Search tracks/), 'xyz');
    expect(await screen.findByText(/Nothing matches your search/)).toBeInTheDocument();
    // Two matches for "Clear search": the X icon in TextInput (svg with role=button)
    // and the EmptyState <Button>. We want the real <button> in the empty state.
    const clearButtons = screen.getAllByRole('button', { name: /Clear search/ });
    const realButton = clearButtons.find((el) => el.tagName === 'BUTTON');
    await userEvent.click(realButton!);
    expect(await screen.findByText('Track t1')).toBeInTheDocument();
  });

  it('bucket-not-found in URL renders empty state', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
    );
    renderAt('/triage/s1/b1/buckets/no-such-id');
    expect(await screen.findByText(/Bucket not found/)).toBeInTheDocument();
  });
});
