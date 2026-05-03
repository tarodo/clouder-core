import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications, notifications } from '@mantine/notifications';
import { ModalsProvider } from '@mantine/modals';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { testTheme } from '../../../../test/theme';
import { tokenStore } from '../../../../auth/tokenStore';
import '../../../../i18n';
import { TransferModal } from '../TransferModal';
import type { TriageBlock } from '../../hooks/useTriageBlock';

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

function r(ui: React.ReactNode, qc = makeClient()) {
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <ModalsProvider>
          <Notifications />
          <MemoryRouter>{ui}</MemoryRouter>
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const srcBlock: TriageBlock = {
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
    { id: 'srcb1', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 3 },
  ],
};

const targetBlock: TriageBlock = {
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
    { id: 'tgtOLD', bucket_type: 'OLD', category_id: null, category_name: null, inactive: false, track_count: 1 },
    { id: 'tgtSTAGING', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Tech', inactive: true, track_count: 0 },
  ],
};

const siblings = {
  items: [
    {
      id: 'tgt1', style_id: 's1', style_name: 'House', name: 'Tgt Block',
      date_from: '2026-04-28', date_to: '2026-05-05',
      status: 'IN_PROGRESS' as const,
      created_at: '2026-04-28T00:00:00Z', updated_at: '2026-04-28T00:00:00Z',
      finalized_at: null, track_count: 1,
    },
    {
      id: 'src1', style_id: 's1', style_name: 'House', name: 'Src Block',
      date_from: '2026-04-21', date_to: '2026-04-28',
      status: 'IN_PROGRESS' as const,
      created_at: '2026-04-21T00:00:00Z', updated_at: '2026-04-21T00:00:00Z',
      finalized_at: null, track_count: 3,
    },
  ],
  total: 2,
  limit: 50,
  offset: 0,
};

beforeEach(() => {
  tokenStore.set('TOK');
  notifications.clean();
});

describe('TransferModal', () => {
  it('step 1 lists siblings excluding current block', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
    );

    r(
      <TransferModal
        opened
        onClose={vi.fn()}
        srcBlock={srcBlock}
        trackIds={['tk1']}
        styleId="s1"
      />,
    );

    expect(await screen.findByText('Tgt Block')).toBeInTheDocument();
    expect(screen.queryByText('Src Block')).toBeNull();
  });

  it('shows EmptyState when only the current block is in IN_PROGRESS', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [siblings.items[1]!],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      ),
    );

    r(
      <TransferModal
        opened
        onClose={vi.fn()}
        srcBlock={srcBlock}
        trackIds={['tk1']}
        styleId="s1"
      />,
    );

    expect(
      await screen.findByText(/No other in-progress blocks/),
    ).toBeInTheDocument();
  });

  it('step 2: clicking a target block loads bucket grid; Back returns to step 1', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
      http.get('http://localhost/triage/blocks/tgt1', () =>
        HttpResponse.json(targetBlock),
      ),
    );

    r(
      <TransferModal
        opened
        onClose={vi.fn()}
        srcBlock={srcBlock}
        trackIds={['tk1']}
        styleId="s1"
      />,
    );

    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));

    await waitFor(() => {
      expect(screen.getByText(/Pick a bucket in/)).toBeInTheDocument();
    });
    // Bucket grid renders 3 buttons (NEW + OLD + inactive STAGING)
    const bucketBtns = screen.getAllByRole('button').filter(
      (b) => /^(Move to NEW|Move to OLD|Move to Tech)/.test(b.getAttribute('aria-label') ?? ''),
    );
    expect(bucketBtns).toHaveLength(3);

    await userEvent.click(screen.getByRole('button', { name: /Back/ }));
    expect(await screen.findByText('Tgt Block')).toBeInTheDocument();
  });

  it('step 2: clicking active NEW bucket POSTs transfer with right payload, fires green toast, closes modal', async () => {
    let bodySeen: unknown = null;
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
      http.get('http://localhost/triage/blocks/tgt1', () =>
        HttpResponse.json(targetBlock),
      ),
      http.post('http://localhost/triage/blocks/src1/transfer', async ({ request }) => {
        bodySeen = await request.json();
        return HttpResponse.json({ transferred: 1 });
      }),
    );
    const onClose = vi.fn();

    r(
      <TransferModal
        opened
        onClose={onClose}
        srcBlock={srcBlock}
        trackIds={['tk1']}
        styleId="s1"
      />,
    );

    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));

    const newBucketBtn = screen.getByRole('button', { name: /Move to NEW/ });
    await userEvent.click(newBucketBtn);

    await waitFor(() => expect(bodySeen).toEqual({ target_bucket_id: 'tgtNEW', track_ids: ['tk1'] }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(await screen.findByText(/Transferred 1 track to Tgt Block/)).toBeInTheDocument();
  });

  it('step 2: inactive STAGING bucket is disabled and does not POST', async () => {
    let posted = false;
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
      http.get('http://localhost/triage/blocks/tgt1', () =>
        HttpResponse.json(targetBlock),
      ),
      http.post('http://localhost/triage/blocks/src1/transfer', () => {
        posted = true;
        return HttpResponse.json({ transferred: 1 });
      }),
    );

    r(
      <TransferModal
        opened
        onClose={vi.fn()}
        srcBlock={srcBlock}
        trackIds={['tk1']}
        styleId="s1"
      />,
    );

    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));

    const stagingBtn = screen.getByRole('button', { name: /Move to Tech \(staging, inactive\)/ });
    expect(stagingBtn).toBeDisabled();
    await userEvent.click(stagingBtn);
    expect(posted).toBe(false);
  });

  it('409 invalid_state: red toast target_finalized + modal closes', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
      http.get('http://localhost/triage/blocks/tgt1', () =>
        HttpResponse.json(targetBlock),
      ),
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json(
          { error_code: 'invalid_state', message: 'finalized' },
          { status: 409 },
        ),
      ),
    );
    const onClose = vi.fn();

    r(
      <TransferModal
        opened
        onClose={onClose}
        srcBlock={srcBlock}
        trackIds={['tk1']}
        styleId="s1"
      />,
    );

    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    await userEvent.click(screen.getByRole('button', { name: /Move to NEW/ }));

    expect(
      await screen.findByText(/Target block was finalized/),
    ).toBeInTheDocument();
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('409 target_bucket_inactive: red toast + STAYS on step 2', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
      http.get('http://localhost/triage/blocks/tgt1', () =>
        HttpResponse.json(targetBlock),
      ),
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json(
          { error_code: 'target_bucket_inactive', message: 'no' },
          { status: 409 },
        ),
      ),
    );
    const onClose = vi.fn();

    r(
      <TransferModal
        opened
        onClose={onClose}
        srcBlock={srcBlock}
        trackIds={['tk1']}
        styleId="s1"
      />,
    );

    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    await userEvent.click(screen.getByRole('button', { name: /Move to NEW/ }));

    expect(await screen.findByText(/no longer valid/)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText(/Pick a bucket in/)).toBeInTheDocument();
  });
});

describe('TransferModal — bulk mode', () => {
  beforeEach(() => {
    server.resetHandlers();
    tokenStore.set('TOK');
    notifications.clean();
  });

  it('mode=bulk, 100 trackIds → 1 chunk, success toast', async () => {
    let postCount = 0;
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
      http.get('http://localhost/triage/blocks/tgt1', () =>
        HttpResponse.json(targetBlock),
      ),
      http.post('http://localhost/triage/blocks/src1/transfer', async ({ request }) => {
        postCount++;
        const body = (await request.json()) as { track_ids: string[] };
        return HttpResponse.json({ transferred: body.track_ids.length }, { status: 200 });
      }),
    );

    const trackIds = Array.from({ length: 100 }, (_, i) => `t${i + 1}`);
    r(
      <TransferModal
        opened
        onClose={vi.fn()}
        srcBlock={srcBlock}
        trackIds={trackIds}
        styleId="s1"
        mode="bulk"
      />,
    );

    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    await userEvent.click(screen.getByRole('button', { name: /Move to NEW/ }));

    await waitFor(() =>
      expect(screen.getByText(/Transferred 100 tracks to .*\/ NEW/i)).toBeInTheDocument(),
    );
    expect(postCount).toBe(1);
  });

  it('mode=bulk, 1500 trackIds → 2 chunks fired sequentially', async () => {
    let postCount = 0;
    let totalTransferred = 0;
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
      http.get('http://localhost/triage/blocks/tgt1', () =>
        HttpResponse.json(targetBlock),
      ),
      http.post('http://localhost/triage/blocks/src1/transfer', async ({ request }) => {
        postCount++;
        const body = (await request.json()) as { track_ids: string[] };
        totalTransferred += body.track_ids.length;
        return HttpResponse.json({ transferred: body.track_ids.length }, { status: 200 });
      }),
    );

    const trackIds = Array.from({ length: 1500 }, (_, i) => `t${i + 1}`);
    r(
      <TransferModal
        opened
        onClose={vi.fn()}
        srcBlock={srcBlock}
        trackIds={trackIds}
        styleId="s1"
        mode="bulk"
      />,
    );

    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    await userEvent.click(screen.getByRole('button', { name: /Move to NEW/ }));

    await waitFor(() =>
      expect(screen.getByText(/Transferred 1500 tracks to/i)).toBeInTheDocument(),
    );
    expect(postCount).toBe(2);
    expect(totalTransferred).toBe(1500);
  });

  it('mode=bulk, mid-chunk error → orange partial toast + modal stays on step 2', async () => {
    let postCount = 0;
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
      http.get('http://localhost/triage/blocks/tgt1', () =>
        HttpResponse.json(targetBlock),
      ),
      http.post('http://localhost/triage/blocks/src1/transfer', async ({ request }) => {
        postCount++;
        if (postCount === 1) {
          const body = (await request.json()) as { track_ids: string[] };
          return HttpResponse.json({ transferred: body.track_ids.length }, { status: 200 });
        }
        return HttpResponse.json(
          { error_code: 'invalid_state', message: 'finalized' },
          { status: 422 },
        );
      }),
    );

    const trackIds = Array.from({ length: 3000 }, (_, i) => `t${i + 1}`);
    r(
      <TransferModal
        opened
        onClose={vi.fn()}
        srcBlock={srcBlock}
        trackIds={trackIds}
        styleId="s1"
        mode="bulk"
      />,
    );

    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    await userEvent.click(screen.getByRole('button', { name: /Move to NEW/ }));

    await waitFor(() =>
      expect(screen.getByText(/Transferred 1000 of 3000/i)).toBeInTheDocument(),
    );
    expect(screen.getByText('← Back')).toBeInTheDocument();
  });
});
