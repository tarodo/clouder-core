import { afterEach, beforeEach, describe, expect, it } from 'vitest';
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
import { TriageDetailPage } from '../routes/TriageDetailPage';
import { BucketDetailPage } from '../routes/BucketDetailPage';

const STAGING_BLOCK = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'Block 1',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS' as const,
  created_at: '2026-04-21T08:00:00Z',
  updated_at: '2026-04-21T08:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'sa', bucket_type: 'STAGING', category_id: 'cA', category_name: 'Tech', inactive: false, track_count: 3 },
    { id: 'sb', bucket_type: 'STAGING', category_id: 'cB', category_name: 'Deep', inactive: false, track_count: 5 },
  ],
};

const BLOCKER_BLOCK = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'Block 1',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS' as const,
  created_at: '2026-04-21T08:00:00Z',
  updated_at: '2026-04-21T08:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'bk1', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 0 },
    { id: 'sa', bucket_type: 'STAGING', category_id: 'cA', category_name: 'Deleted Cat', inactive: true, track_count: 4 },
  ],
};

const FINALIZED_BLOCK = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'Block 1',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'FINALIZED' as const,
  created_at: '2026-04-21T08:00:00Z',
  updated_at: '2026-04-21T08:00:00Z',
  finalized_at: '2026-04-29T00:00:00Z',
  buckets: [
    { id: 'bk1', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 75 },
    { id: 'bk3', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Tech', inactive: false, track_count: 0 },
  ],
};

const TARGET_BLOCK = {
  id: 'b2',
  style_id: 's1',
  style_name: 'House',
  name: 'Target Block',
  date_from: '2026-04-28',
  date_to: '2026-05-05',
  status: 'IN_PROGRESS' as const,
  created_at: '2026-04-28T00:00:00Z',
  updated_at: '2026-04-28T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'tgtNEW', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 0 },
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
    label_name: null,
    added_at: '2026-04-21T08:00:00Z',
  };
}

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

function mountTriageDetail(blockId: string) {
  return render(
    <QueryClientProvider client={makeClient()}>
      <MantineProvider theme={testTheme}>
        <ModalsProvider>
          <Notifications />
          <MemoryRouter initialEntries={[`/triage/s1/${blockId}`]}>
            <Routes>
              <Route path="/triage/:styleId/:id" element={<TriageDetailPage />} />
              <Route
                path="/triage/:styleId/:id/buckets/:bucketId"
                element={<div data-testid="bucket-page" />}
              />
              <Route path="/triage/:styleId" element={<div data-testid="list-page" />} />
            </Routes>
          </MemoryRouter>
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

function mountBucketDetail(blockId: string, bucketId: string) {
  return render(
    <QueryClientProvider client={makeClient()}>
      <MantineProvider theme={testTheme}>
        <ModalsProvider>
          <Notifications />
          <MemoryRouter initialEntries={[`/triage/s1/${blockId}/buckets/${bucketId}`]}>
            <Routes>
              <Route
                path="/triage/:styleId/:id/buckets/:bucketId"
                element={<BucketDetailPage />}
              />
              <Route path="/triage/:styleId/:id" element={<div data-testid="block-page" />} />
              <Route path="/triage/:styleId" element={<div data-testid="list-page" />} />
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
});
afterEach(() => {
  notifications.clean();
  server.resetHandlers();
});

describe('FinalizeFlow integration', () => {
  it('happy path: STAGING block → Finalize button → confirm modal → POST 200 → green toast', async () => {
    let postBodySeen = false;
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(STAGING_BLOCK)),
      http.post('http://localhost/triage/blocks/b1/finalize', () => {
        postBodySeen = true;
        return HttpResponse.json(
          {
            block: { ...STAGING_BLOCK, status: 'FINALIZED', finalized_at: '2026-04-29T00:00:00Z' },
            promoted: { cA: 3, cB: 5 },
          },
          { status: 200 },
        );
      }),
    );

    mountTriageDetail('b1');

    // Wait for header; then open Finalize modal
    await screen.findByText('Block 1');
    await userEvent.click(screen.getByRole('button', { name: 'Finalize' }));

    // Confirm modal: title + 2 summary rows + total
    expect(await screen.findByText(/Finalize Block 1\?/i)).toBeInTheDocument();
    expect(screen.getByText('Tech')).toBeInTheDocument();
    expect(screen.getByText('Deep')).toBeInTheDocument();
    expect(screen.getByText('+3 tracks')).toBeInTheDocument();
    expect(screen.getByText('+5 tracks')).toBeInTheDocument();
    expect(
      screen.getByText(/8 tracks will be promoted into 2 categories/i),
    ).toBeInTheDocument();

    // Submit — there are two "Finalize" buttons after modal opens (header + modal submit).
    // Pick the modal submit button (last one, inside the modal dialog).
    const finalizeButtons = screen.getAllByRole('button', { name: 'Finalize' });
    const modalSubmit = finalizeButtons[finalizeButtons.length - 1]!;
    await userEvent.click(modalSubmit);

    await waitFor(() => expect(postBodySeen).toBe(true));
    expect(
      await screen.findByText(/Finalized Block 1.*promoted 8 tracks across 2 categories/i),
    ).toBeInTheDocument();

    // Modal closes — confirm body text gone
    await waitFor(() =>
      expect(
        screen.queryByText(/8 tracks will be promoted into 2 categories/i),
      ).not.toBeInTheDocument(),
    );
  });

  it('blocker preempt: inactive STAGING with tracks → blocker variant + Open link', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(BLOCKER_BLOCK)),
    );

    mountTriageDetail('b1');

    await screen.findByText('Block 1');
    await userEvent.click(screen.getByRole('button', { name: 'Finalize' }));

    expect(await screen.findByText('Cannot finalize yet')).toBeInTheDocument();
    expect(screen.getByText('Deleted Cat')).toBeInTheDocument();
    expect(screen.getByText('4 tracks')).toBeInTheDocument();
    const openLink = screen.getByRole('link', { name: 'Open' });
    expect(openLink).toHaveAttribute('href', '/triage/s1/b1/buckets/sa');
  });

  it('bulk transfer happy path: FINALIZED + NEW bucket w/ 75 tracks → drains 2 pages → POST → success toast', async () => {
    const trackRequests: number[] = [];
    let postBody: { target_bucket_id: string; track_ids: string[] } | null = null;
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(FINALIZED_BLOCK)),
      http.get('http://localhost/triage/blocks/b2', () => HttpResponse.json(TARGET_BLOCK)),
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', ({ request }) => {
        const url = new URL(request.url);
        const offset = Number(url.searchParams.get('offset') ?? '0');
        trackRequests.push(offset);
        if (offset === 0) {
          const items = Array.from({ length: 50 }, (_, i) => track(`t${i}`));
          return HttpResponse.json({ items, total: 75, limit: 50, offset: 0 });
        }
        const items = Array.from({ length: 25 }, (_, i) => track(`t${50 + i}`));
        return HttpResponse.json({ items, total: 75, limit: 50, offset: 50 });
      }),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [
            {
              id: 'b2', style_id: 's1', style_name: 'House', name: 'Target Block',
              date_from: '2026-04-28', date_to: '2026-05-05',
              status: 'IN_PROGRESS' as const,
              created_at: '2026-04-28T00:00:00Z', updated_at: '2026-04-28T00:00:00Z',
              finalized_at: null, track_count: 0,
            },
          ],
          total: 1, limit: 50, offset: 0,
        }),
      ),
      http.post('http://localhost/triage/blocks/b1/transfer', async ({ request }) => {
        postBody = (await request.json()) as { target_bucket_id: string; track_ids: string[] };
        return HttpResponse.json({ transferred: postBody.track_ids.length }, { status: 200 });
      }),
    );

    mountBucketDetail('b1', 'bk1');

    // First page renders
    await screen.findByText('Track t0');

    // Click bulk CTA
    await userEvent.click(
      await screen.findByRole('button', { name: /Transfer all to another block/i }),
    );

    // Drains 2nd page (offset=50)
    await waitFor(() => expect(trackRequests).toContain(50));

    // Modal opens at step 1 — sibling block visible
    await userEvent.click(await screen.findByRole('button', { name: /Target Block/ }));

    // Step 2: target bucket grid loaded
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    await userEvent.click(screen.getByRole('button', { name: /Move to NEW/ }));

    // POST sent with all 75 ids in one chunk
    await waitFor(() => expect(postBody).not.toBeNull());
    expect(postBody!.target_bucket_id).toBe('tgtNEW');
    expect(postBody!.track_ids).toHaveLength(75);

    // Green toast — bulk uses success template
    expect(
      await screen.findByText(/Transferred 75 tracks to Target Block.*NEW/i),
    ).toBeInTheDocument();

    // Modal closes
    await waitFor(() => expect(screen.queryByText(/Pick a bucket in/)).toBeNull());
  });

  it('gating: FINALIZED block + STAGING bucket — bulk transfer button absent', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(FINALIZED_BLOCK)),
      http.get('http://localhost/triage/blocks/b1/buckets/bk3/tracks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );

    mountBucketDetail('b1', 'bk3');

    // Header renders for STAGING bucket
    await screen.findByRole('heading', { name: /Tech/ });
    expect(
      screen.queryByRole('button', { name: /Transfer all to another block/i }),
    ).not.toBeInTheDocument();
  });

  it('gating: FINALIZED block — Finalize button absent in TriageBlockHeader', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(FINALIZED_BLOCK)),
    );

    mountTriageDetail('b1');

    // Header status badge renders
    await screen.findByText('FINALIZED');
    expect(screen.queryByRole('button', { name: 'Finalize' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Delete block/ })).not.toBeInTheDocument();
  });
});
