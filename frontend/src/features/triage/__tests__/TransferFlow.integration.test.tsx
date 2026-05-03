import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications, notifications } from '@mantine/notifications';
import { ModalsProvider } from '@mantine/modals';
import { MemoryRouter, Routes, Route } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/setup';
import { testTheme } from '../../../test/theme';
import { tokenStore } from '../../../auth/tokenStore';
import '../../../i18n';
import { BucketDetailPage } from '../routes/BucketDetailPage';

const SRC_BLOCK = {
  id: 'src1',
  style_id: 's1',
  style_name: 'House',
  name: 'Src Block',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS',
  created_at: '2026-04-21T00:00:00Z',
  updated_at: '2026-04-21T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'srcNEW', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 1 },
  ],
};

const TGT_BLOCK = {
  id: 'tgt1',
  style_id: 's1',
  style_name: 'House',
  name: 'Tgt Block',
  date_from: '2026-04-28',
  date_to: '2026-05-05',
  status: 'IN_PROGRESS',
  created_at: '2026-04-28T00:00:00Z',
  updated_at: '2026-04-28T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'tgtNEW', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 0 },
    { id: 'tgtSTAGING', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Tech', inactive: true, track_count: 0 },
  ],
};

const TRACK = {
  track_id: 'tk1',
  title: 'Some Title',
  mix_name: null,
  isrc: null,
  bpm: 128,
  length_ms: 240000,
  publish_date: null,
  spotify_release_date: '2026-04-15',
  spotify_id: null,
  release_type: null,
  is_ai_suspected: false,
  artists: ['Artist'],
  added_at: '2026-04-21T00:00:00Z',
};

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

function r(qc = makeClient()) {
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <ModalsProvider>
          <Notifications />
          <MemoryRouter initialEntries={['/triage/s1/src1/buckets/srcNEW']}>
            <Routes>
              <Route
                path="/triage/:styleId/:id/buckets/:bucketId"
                element={<BucketDetailPage />}
              />
              <Route path="/triage/:styleId" element={<div>triage list</div>} />
            </Routes>
          </MemoryRouter>
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  tokenStore.set('TOK');
  notifications.clean();
  // Default handlers — individual tests override as needed.
  server.use(
    http.get('http://localhost/triage/blocks/src1', () => HttpResponse.json(SRC_BLOCK)),
    http.get('http://localhost/triage/blocks/tgt1', () => HttpResponse.json(TGT_BLOCK)),
    http.get('http://localhost/triage/blocks/src1/buckets/srcNEW/tracks', () =>
      HttpResponse.json({ items: [TRACK], total: 1, limit: 50, offset: 0 }),
    ),
    http.get('http://localhost/styles/s1/triage/blocks', () =>
      HttpResponse.json({
        items: [
          {
            id: 'tgt1', style_id: 's1', style_name: 'House', name: 'Tgt Block',
            date_from: '2026-04-28', date_to: '2026-05-05',
            status: 'IN_PROGRESS' as const,
            created_at: '2026-04-28T00:00:00Z', updated_at: '2026-04-28T00:00:00Z',
            finalized_at: null, track_count: 0,
          },
          {
            id: 'src1', style_id: 's1', style_name: 'House', name: 'Src Block',
            date_from: '2026-04-21', date_to: '2026-04-28',
            status: 'IN_PROGRESS' as const,
            created_at: '2026-04-21T00:00:00Z', updated_at: '2026-04-21T00:00:00Z',
            finalized_at: null, track_count: 1,
          },
        ],
        total: 2,
        limit: 50,
        offset: 0,
      }),
    ),
  );
});

describe('Transfer flow integration', () => {
  it('happy path: row kebab → Transfer → block → bucket → toast', async () => {
    let bodySeen: unknown = null;
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', async ({ request }) => {
        bodySeen = await request.json();
        return HttpResponse.json({ transferred: 1 });
      }),
    );

    r();

    await screen.findByText('Some Title');

    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(
      await screen.findByRole('menuitem', { name: /Transfer to other block/ }),
    );

    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));

    await waitFor(() => screen.getByText(/Pick a bucket in/));
    const newBtn = screen.getByRole('button', { name: /Move to NEW/ });
    await userEvent.click(newBtn);

    await waitFor(() =>
      expect(bodySeen).toEqual({ target_bucket_id: 'tgtNEW', track_ids: ['tk1'] }),
    );
    expect(await screen.findByText(/Transferred 1 track to Tgt Block/)).toBeInTheDocument();
  });

  it('empty siblings: shows EmptyState with CTA', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [{
            id: 'src1', style_id: 's1', style_name: 'House', name: 'Src Block',
            date_from: '2026-04-21', date_to: '2026-04-28',
            status: 'IN_PROGRESS', created_at: '2026-04-21T00:00:00Z',
            updated_at: '2026-04-21T00:00:00Z', finalized_at: null, track_count: 1,
          }],
          total: 1, limit: 50, offset: 0,
        }),
      ),
    );

    r();
    await screen.findByText('Some Title');
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Transfer to other block/ }));

    expect(await screen.findByText(/No other in-progress blocks/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Go to triage/ })).toBeInTheDocument();
  });

  it('inactive STAGING bucket disabled in step 2', async () => {
    let posted = false;
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', () => {
        posted = true;
        return HttpResponse.json({ transferred: 1 });
      }),
    );

    r();
    await screen.findByText('Some Title');
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Transfer to other block/ }));
    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));

    const stagingBtn = screen.getByRole('button', { name: /Move to Tech \(staging, inactive\)/ });
    expect(stagingBtn).toBeDisabled();
    await userEvent.click(stagingBtn);
    expect(posted).toBe(false);
  });

  it('409 invalid_state: red toast, modal closes', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json(
          { error_code: 'invalid_state', message: 'finalized' },
          { status: 409 },
        ),
      ),
    );

    r();
    await screen.findByText('Some Title');
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Transfer to other block/ }));
    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    await userEvent.click(screen.getByRole('button', { name: /Move to NEW/ }));

    expect(await screen.findByText(/Target block was finalized/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(/Pick a bucket in/)).toBeNull());
  });

  it('409 target_bucket_inactive: red toast, modal stays on step 2', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json(
          { error_code: 'target_bucket_inactive', message: 'no' },
          { status: 409 },
        ),
      ),
    );

    r();
    await screen.findByText('Some Title');
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Transfer to other block/ }));
    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    await userEvent.click(screen.getByRole('button', { name: /Move to NEW/ }));

    expect(await screen.findByText(/no longer valid/)).toBeInTheDocument();
    expect(screen.getByText(/Pick a bucket in/)).toBeInTheDocument();
  });

  it('FINALIZED src block: Transfer item not exposed', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/src1', () =>
        HttpResponse.json({ ...SRC_BLOCK, status: 'FINALIZED', finalized_at: '2026-04-29T00:00:00Z' }),
      ),
    );

    r();
    await screen.findByText('Some Title');
    expect(screen.queryByRole('button', { name: /Move track/ })).toBeNull();
    expect(screen.queryByText(/Transfer to other block/)).toBeNull();
  });

  it('Back from step 2 returns to step 1 without re-fetching siblings', async () => {
    let siblingsCallCount = 0;
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () => {
        siblingsCallCount += 1;
        return HttpResponse.json({
          items: [
            {
              id: 'tgt1', style_id: 's1', style_name: 'House', name: 'Tgt Block',
              date_from: '2026-04-28', date_to: '2026-05-05',
              status: 'IN_PROGRESS' as const,
              created_at: '2026-04-28T00:00:00Z', updated_at: '2026-04-28T00:00:00Z',
              finalized_at: null, track_count: 0,
            },
          ],
          total: 1, limit: 50, offset: 0,
        });
      }),
    );

    r();
    await screen.findByText('Some Title');
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Transfer to other block/ }));
    await screen.findByRole('button', { name: /Tgt Block/ });
    expect(siblingsCallCount).toBe(1);

    await userEvent.click(screen.getByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    await userEvent.click(screen.getByRole('button', { name: /Back/ }));

    expect(await screen.findByRole('button', { name: /Tgt Block/ })).toBeInTheDocument();
    // No additional siblings fetch on Back.
    expect(siblingsCallCount).toBe(1);
  });

  it('404 tracks_not_in_source: red toast stale_source + modal closes', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json(
          { error_code: 'tracks_not_in_source', message: 'gone' },
          { status: 404 },
        ),
      ),
    );

    r();
    await screen.findByText('Some Title');
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Transfer to other block/ }));
    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    await userEvent.click(screen.getByRole('button', { name: /Move to NEW/ }));

    expect(await screen.findByText(/Source block changed/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(/Pick a bucket in/)).toBeNull());
  });

  it('404 target_bucket_not_found: red toast stale_target + returns to step 1', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json(
          { error_code: 'target_bucket_not_found', message: 'gone' },
          { status: 404 },
        ),
      ),
    );

    r();
    await screen.findByText('Some Title');
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Transfer to other block/ }));
    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    await userEvent.click(screen.getByRole('button', { name: /Move to NEW/ }));

    expect(await screen.findByText(/Target block is gone/)).toBeInTheDocument();
    // Modal stays open but returns to step 1 (sibling list visible again).
    expect(await screen.findByText(/Transfer to which block/)).toBeInTheDocument();
  });

  it('503 terminal: red network toast + STAYS on step 2 (retry on second click works)', async () => {
    let attempts = 0;
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', () => {
        attempts += 1;
        if (attempts === 1) {
          return HttpResponse.json(
            { error_code: 'unknown', message: 'Service Unavailable' },
            { status: 503 },
          );
        }
        return HttpResponse.json({ transferred: 1 });
      }),
    );

    r();
    await screen.findByText('Some Title');
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Transfer to other block/ }));
    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));

    // First click → 503
    await userEvent.click(screen.getByRole('button', { name: /Move to NEW/ }));
    expect(await screen.findByText(/Connection lost/)).toBeInTheDocument();
    // Modal stays — Pick a bucket title still visible
    expect(screen.getByText(/Pick a bucket in/)).toBeInTheDocument();

    // Second click → 200 OK, modal closes, success toast
    await userEvent.click(screen.getByRole('button', { name: /Move to NEW/ }));
    expect(await screen.findByText(/Transferred 1 track to Tgt Block/)).toBeInTheDocument();
  });
});
