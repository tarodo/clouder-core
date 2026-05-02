import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications, notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router';

// Mantine's DatePickerInput renders as a button-like trigger that opens a
// popover calendar — userEvent.type cannot drive it under jsdom. Replace with
// a plain text input that parses "YYYY-MM-DD – YYYY-MM-DD" and forwards a
// [Date, Date] tuple to the form, matching the production onChange contract.
// (Same shape as components/__tests__/CreateTriageBlockDialog.test.tsx.)
vi.mock('@mantine/dates', async () => {
  const React = await import('react');
  type Props = {
    label?: string;
    onChange?: (value: [Date | null, Date | null]) => void;
    error?: React.ReactNode;
    description?: React.ReactNode;
    placeholder?: string;
  };
  const DatePickerInput = ({
    label,
    onChange,
    error,
    description,
    placeholder,
  }: Props) => {
    const [text, setText] = React.useState('');
    return (
      <div>
        <label>
          {label}
          <input
            type="text"
            placeholder={placeholder}
            value={text}
            onChange={(e) => {
              const raw = e.target.value;
              setText(raw);
              const parts = raw.split(' – ');
              if (parts.length === 2 && parts[0] && parts[1]) {
                const a = new Date(parts[0].trim());
                const b = new Date(parts[1].trim());
                if (
                  !Number.isNaN(a.getTime()) &&
                  !Number.isNaN(b.getTime())
                ) {
                  onChange?.([a, b]);
                  return;
                }
              }
              onChange?.([null, null]);
            }}
          />
        </label>
        {description ? <div>{description}</div> : null}
        {error ? <div role="alert">{error}</div> : null}
      </div>
    );
  };
  return { DatePickerInput };
});

import { TriageListPage } from '../routes/TriageListPage';

const server = setupServer();
beforeEach(() => {
  server.listen({ onUnhandledRequest: 'error' });
  // Mantine notifications use a global store — clear between tests so toasts
  // from a previous test do not bleed into the next one.
  notifications.clean();
});
afterEach(() => {
  server.resetHandlers();
  server.close();
  notifications.clean();
});

function renderApp(initialPath = '/triage/s1') {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <MantineProvider>
        <QueryClientProvider client={qc}>
          <ModalsProvider>
            <Notifications />
            <Routes>
              <Route path="/triage/:styleId" element={<TriageListPage />} />
            </Routes>
          </ModalsProvider>
        </QueryClientProvider>
      </MantineProvider>
    </MemoryRouter>,
  );
}

const stylesResponse = {
  items: [{ id: 's1', name: 'House' }],
  total: 1,
  limit: 200,
  offset: 0,
};

const sampleBlock = (overrides = {}) => ({
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'House W17',
  date_from: '2026-04-20',
  date_to: '2026-04-26',
  status: 'IN_PROGRESS',
  created_at: '2026-04-20T10:00:00Z',
  updated_at: '2026-04-20T10:00:00Z',
  finalized_at: null,
  track_count: 12,
  ...overrides,
});

describe('TriageListPage integration', () => {
  it('happy create + delete', async () => {
    let blocks = [sampleBlock()];
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json(stylesResponse),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        const status = new URL(request.url).searchParams.get('status');
        const filtered =
          status === 'FINALIZED'
            ? blocks.filter((b) => b.status === 'FINALIZED')
            : status === 'IN_PROGRESS'
              ? blocks.filter((b) => b.status === 'IN_PROGRESS')
              : blocks;
        return HttpResponse.json({
          items: filtered,
          total: filtered.length,
          limit: 50,
          offset: 0,
        });
      }),
      http.post('http://localhost/triage/blocks', async ({ request }) => {
        const body = (await request.json()) as Record<string, string>;
        const created = sampleBlock({
          id: 'b2',
          name: body.name,
          date_from: body.date_from,
          date_to: body.date_to,
          track_count: 0,
        });
        blocks = [created, ...blocks];
        return HttpResponse.json(created, { status: 201 });
      }),
      http.delete('http://localhost/triage/blocks/b1', () => {
        blocks = blocks.filter((b) => b.id !== 'b1');
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderApp();
    // Mantine Tabs renders inactive panels in the DOM (hidden), so the
    // initial-render block appears in BOTH the Active and the All panels.
    // Use findAllByText for the assertion.
    const initial = await screen.findAllByText('House W17');
    expect(initial.length).toBeGreaterThanOrEqual(1);

    await userEvent.click(
      screen.getByRole('button', { name: /New triage block/i }),
    );
    const dateInput = await screen.findByLabelText('Window');
    await userEvent.type(dateInput, '2026-05-01 – 2026-05-07');
    await waitFor(() => {
      const name = screen.getByLabelText('Name') as HTMLInputElement;
      expect(name.value).toContain('W18');
    });
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    await screen.findByText(/Triage block created\.$/i);

    // Wait for the new block to appear (refetch landed). The newer "House W18"
    // is prepended; the original "House W17" should still be visible too.
    await screen.findAllByText('House W18');
    expect(screen.getAllByText('House W17').length).toBeGreaterThanOrEqual(1);

    // Delete the original block via its kebab. Mantine renders all Tabs
    // panels (active + finalized + all) and each visible row has a kebab,
    // so getAllByRole returns >= 4 (W18-active, W17-active, W18-all, W17-all).
    // Pick the W17 kebab on the active panel — it is the second kebab in the
    // active panel rows (W18 prepended). aria-hidden tab panels are still
    // present in DOM but `getByRole` filters by accessibility tree visibility.
    const kebabs = screen.getAllByRole('button', { name: /menu/i });
    expect(kebabs.length).toBeGreaterThanOrEqual(2);
    // The active panel is mounted first; its second kebab is W17's.
    const w17Kebab = kebabs[1];
    if (!w17Kebab) throw new Error('W17 kebab not found');
    await userEvent.click(w17Kebab);
    await userEvent.click(
      await screen.findByRole('menuitem', { name: 'Delete' }),
    );
    // Confirmation modal appears with another "Delete" button (role=button).
    const confirmButtons = await screen.findAllByRole('button', {
      name: 'Delete',
    });
    const lastConfirm = confirmButtons[confirmButtons.length - 1];
    if (!lastConfirm) throw new Error('confirm button not found');
    await userEvent.click(lastConfirm);
    await waitFor(() =>
      expect(screen.queryByText('House W17')).not.toBeInTheDocument(),
    );
  });

  it('503 create — yellow toast surfaces "taking longer than usual"', async () => {
    // Background recovery from 503 polls on real timers (15s, 30s) which we
    // don't drive here — the assertion is just that the user-facing toast
    // appears synchronously when the POST returns 503. The post-hoc
    // "created (it took a moment)" path is exercised by the unit suite for
    // pendingCreateRecovery.
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json(stylesResponse),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
      http.post('http://localhost/triage/blocks', () =>
        HttpResponse.json({ message: 'Service Unavailable' }, { status: 503 }),
      ),
    );

    renderApp();
    await userEvent.click(
      await screen.findByRole('button', { name: /New triage block/i }),
    );
    const dateInput = await screen.findByLabelText('Window');
    await userEvent.type(dateInput, '2026-05-01 – 2026-05-07');
    await waitFor(() => {
      const name = screen.getByLabelText('Name') as HTMLInputElement;
      expect(name.value).toContain('W18');
    });
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    expect(
      await screen.findByText(/taking longer than usual/i),
    ).toBeInTheDocument();
  });

  it('503 create — recovery refetch eventually surfaces success toast', async () => {
    // pendingCreateRecovery uses setTimeout(fn, 0) for the first tick, so we
    // can rely on real timers here. The 0ms tick refetches, finds the block
    // in the cache, and fires the success notification.
    let listResponseBlocks: ReturnType<typeof sampleBlock>[] = [];
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json(stylesResponse),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: listResponseBlocks,
          total: listResponseBlocks.length,
          limit: 50,
          offset: 0,
        }),
      ),
      http.post('http://localhost/triage/blocks', () => {
        // Simulate API GW 29s timeout case: client sees 503 but the Lambda
        // completed in the background — block shows up on subsequent GETs.
        listResponseBlocks = [
          sampleBlock({
            id: 'eventually',
            name: 'House W18',
            date_from: '2026-05-01',
            date_to: '2026-05-07',
            track_count: 0,
          }),
        ];
        return HttpResponse.json(
          { message: 'Service Unavailable' },
          { status: 503 },
        );
      }),
    );

    renderApp();
    await userEvent.click(
      await screen.findByRole('button', { name: /New triage block/i }),
    );
    const dateInput = await screen.findByLabelText('Window');
    fireEvent.change(dateInput, {
      target: { value: '2026-05-01 – 2026-05-07' },
    });
    await waitFor(() => {
      const name = screen.getByLabelText('Name') as HTMLInputElement;
      expect(name.value).toContain('W18');
    });
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));

    // First the yellow "pending" toast surfaces synchronously.
    expect(
      await screen.findByText(/taking longer than usual/i),
    ).toBeInTheDocument();

    // The 0ms recovery tick refetches, sees the block, and fires the
    // success notification. Wait up to 3s for the toast to appear.
    await waitFor(
      () =>
        expect(
          screen.getByText(/created \(it took a moment\)/i),
        ).toBeInTheDocument(),
      { timeout: 3000 },
    );
  });
});
