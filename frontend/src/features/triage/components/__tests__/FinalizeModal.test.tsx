import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications, notifications } from '@mantine/notifications';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { testTheme } from '../../../../test/theme';
import '../../../../i18n';
import { FinalizeModal } from '../FinalizeModal';
import type { TriageBlock } from '../../hooks/useTriageBlock';

function block(overrides: Partial<TriageBlock> = {}): TriageBlock {
  return {
    id: 'b1',
    style_id: 's1',
    style_name: 'House',
    name: 'Block 1',
    date_from: '2026-04-21',
    date_to: '2026-04-28',
    status: 'IN_PROGRESS',
    created_at: '2026-04-21T00:00:00Z',
    updated_at: '2026-04-21T00:00:00Z',
    finalized_at: null,
    buckets: [],
    ...overrides,
  };
}

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

function r(blockArg: TriageBlock, onClose = () => {}, qc = makeClient()) {
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <Notifications />
        <MemoryRouter>
          <FinalizeModal opened onClose={onClose} block={blockArg} styleId="s1" />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  notifications.clean();
  server.resetHandlers();
});

describe('FinalizeModal — confirm variant', () => {
  it('renders empty-summary copy when block has no STAGING buckets', () => {
    r(block({ buckets: [] }));
    expect(screen.getByText(/no staging buckets/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Finalize' })).toBeEnabled();
  });

  it('renders summary rows + total when STAGING buckets are present', () => {
    r(
      block({
        buckets: [
          { id: 'sa', bucket_type: 'STAGING', category_id: 'cA', category_name: 'A', inactive: false, track_count: 3 },
          { id: 'sb', bucket_type: 'STAGING', category_id: 'cB', category_name: 'B', inactive: false, track_count: 5 },
        ],
      }),
    );
    expect(screen.getByText('A')).toBeInTheDocument();
    expect(screen.getByText('B')).toBeInTheDocument();
    expect(screen.getByText('+3 tracks')).toBeInTheDocument();
    expect(screen.getByText('+5 tracks')).toBeInTheDocument();
    expect(screen.getByText(/8 tracks will be promoted into 2 categories/i)).toBeInTheDocument();
  });

  it('fires green success toast on 200 OK and closes modal', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/b1/finalize', () =>
        HttpResponse.json(
          {
            block: { ...block(), status: 'FINALIZED', finalized_at: '2026-04-29T00:00:00Z' },
            promoted: { cA: 3, cB: 5 },
          },
          { status: 200 },
        ),
      ),
    );
    const user = userEvent.setup();
    const onClose = vi.fn();
    r(
      block({
        buckets: [
          { id: 'sa', bucket_type: 'STAGING', category_id: 'cA', category_name: 'A', inactive: false, track_count: 3 },
          { id: 'sb', bucket_type: 'STAGING', category_id: 'cB', category_name: 'B', inactive: false, track_count: 5 },
        ],
      }),
      onClose,
    );
    await user.click(screen.getByRole('button', { name: 'Finalize' }));
    await waitFor(() =>
      expect(screen.getByText(/Finalized Block 1.*promoted 8 tracks across 2 categories/i)).toBeInTheDocument(),
    );
    expect(onClose).toHaveBeenCalled();
  });

  it('shows red toast and closes modal on 422 invalid_state', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/b1/finalize', () =>
        HttpResponse.json(
          { error_code: 'invalid_state', message: 'block is not editable' },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    const onClose = vi.fn();
    r(block(), onClose);
    await user.click(screen.getByRole('button', { name: 'Finalize' }));
    await waitFor(() => expect(screen.getByText(/already finalized/i)).toBeInTheDocument());
    expect(onClose).toHaveBeenCalled();
  });

  it('flips to blocker variant on 409 with inactive_buckets payload', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/b1/finalize', () =>
        HttpResponse.json(
          {
            error_code: 'inactive_buckets_have_tracks',
            message: '1 inactive staging holds tracks',
            inactive_buckets: [{ id: 'bkX', category_id: 'cX', track_count: 4 }],
          },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    r(block());
    await user.click(screen.getByRole('button', { name: 'Finalize' }));
    await waitFor(() => expect(screen.getByText('Cannot finalize yet')).toBeInTheDocument());
    expect(screen.getByText('4 tracks')).toBeInTheDocument();
  });
});

describe('FinalizeModal — blocker variant (preempt)', () => {
  it('renders blocker variant when local block has inactive STAGING with tracks', () => {
    r(
      block({
        buckets: [
          { id: 'sa', bucket_type: 'STAGING', category_id: 'cA', category_name: 'Deleted Cat', inactive: true, track_count: 9 },
        ],
      }),
    );
    expect(screen.getByText('Cannot finalize yet')).toBeInTheDocument();
    expect(screen.getByText('Deleted Cat')).toBeInTheDocument();
    expect(screen.getByText('9 tracks')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Finalize' })).toBeDisabled();
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute(
      'href',
      '/triage/s1/b1/buckets/sa',
    );
  });
});

describe('FinalizeModal — 503 cold-start recovery', () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  it('switches to recovering phase on 503; success on poll flip', async () => {
    let getCount = 0;
    server.use(
      http.post('http://localhost/triage/blocks/b1/finalize', () =>
        HttpResponse.json({ message: 'Service Unavailable' }, { status: 503 }),
      ),
      http.get('http://localhost/triage/blocks/b1', () => {
        getCount++;
        if (getCount === 1) {
          return HttpResponse.json({ ...block(), status: 'IN_PROGRESS' });
        }
        return HttpResponse.json({
          ...block(),
          status: 'FINALIZED',
          finalized_at: '2026-04-29T00:00:00Z',
        });
      }),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    r(block(), onClose);
    await user.click(screen.getByRole('button', { name: 'Finalize' }));
    // tick 1 (t=0)
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByText(/cold start, hang on/i)).toBeInTheDocument();
    // tick 2 (t=15s) → FINALIZED
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() =>
      expect(screen.getByText(/Finalize succeeded after retry/i)).toBeInTheDocument(),
    );
    expect(onClose).toHaveBeenCalled();
  });
});
