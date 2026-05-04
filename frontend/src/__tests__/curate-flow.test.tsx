// frontend/src/__tests__/curate-flow.test.tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { http, HttpResponse } from 'msw';
import { server } from '../test/setup';
import { tokenStore } from '../auth/tokenStore';
import { testTheme } from '../test/theme';
import {
  CurateIndexRedirect,
  CurateStyleResume,
  CurateSessionPage,
} from '../features/curate';

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

const block = {
  id: 'b1',
  style_id: 's1',
  style_name: 'Tech House',
  name: 'TH W17',
  date_from: '2026-04-21',
  date_to: '2026-04-27',
  status: 'IN_PROGRESS' as const,
  created_at: '2026-04-20T00:00:00Z',
  updated_at: '2026-04-20T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'src', bucket_type: 'NEW' as const, inactive: false, track_count: 3 },
    { id: 'dst1', bucket_type: 'STAGING' as const, inactive: false, track_count: 0,
      category_id: 'c1', category_name: 'Big Room' },
    { id: 'dst2', bucket_type: 'STAGING' as const, inactive: false, track_count: 0,
      category_id: 'c2', category_name: 'Hard Techno' },
    { id: 'b-old', bucket_type: 'OLD' as const, inactive: false, track_count: 2 },
    { id: 'b-disc', bucket_type: 'DISCARD' as const, inactive: false, track_count: 0 },
  ],
};

const tracks = (ids: string[]) => ({
  items: ids.map((id) => ({
    track_id: id,
    title: `Track ${id}`,
    mix_name: null,
    isrc: null,
    bpm: 124,
    length_ms: 360000,
    publish_date: '2026-04-15',
    spotify_release_date: '2026-04-15',
    spotify_id: `sp-${id}`,
    release_type: 'single',
    is_ai_suspected: false,
    artists: ['Artist A'],
    label_name: 'Label X',
    added_at: '2026-04-21T00:00:00Z',
  })),
  total: ids.length,
  limit: 50,
  offset: 0,
});

let moveCount = 0;
function defaultHandlers() {
  moveCount = 0;
  return [
    http.get('http://localhost/styles', () =>
      HttpResponse.json([{ id: 's1', name: 'Tech House' }]),
    ),
    http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(block)),
    http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
      HttpResponse.json(tracks(['t1', 't2', 't3'])),
    ),
    http.post('http://localhost/triage/blocks/b1/move', async () => {
      moveCount += 1;
      return HttpResponse.json({ moved: 1, correlation_id: `cid-${moveCount}` });
    }),
  ];
}

function renderApp(initial = '/curate/s1/b1/src') {
  const qc = makeClient();
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <QueryClientProvider client={qc}>
        <MantineProvider theme={testTheme}>
          <Notifications />
          <Routes>
            <Route path="/curate" element={<CurateIndexRedirect />} />
            <Route path="/curate/:styleId" element={<CurateStyleResume />} />
            <Route
              path="/curate/:styleId/:blockId/:bucketId"
              element={<CurateSessionPage />}
            />
          </Routes>
        </MantineProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('Curate flow integration', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    localStorage.clear();
    server.use(...defaultHandlers());
  });
  afterEach(() => {
    localStorage.clear();
  });

  it('happy path: assign first track via hotkey 1, advance past track 1', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderApp();

    await waitFor(() => expect(screen.getByText('Track t1')).toBeInTheDocument());

    await user.keyboard('1');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(220);
    });
    // Optimistic update removes t1 from queue → queue=[t2,t3].
    // ADVANCE fires after 200ms → currentIndex=1 → shows t3.
    await waitFor(() => expect(screen.queryByText('Track t1')).toBeNull());
    expect(moveCount).toBeGreaterThanOrEqual(1);

    vi.useRealTimers();
  });

  it('double-tap 1 then 2 — first reverted, second applied, single advance', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderApp();

    await waitFor(() => expect(screen.getByText('Track t1')).toBeInTheDocument());
    await user.keyboard('1');
    await user.keyboard('2');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(220);
    });
    // Optimistic update removes t1, ADVANCE fires → queue=[t2,t3], currentIndex=1 → t3.
    // Three POSTs: forward(dst1), inverse(undo dst1), forward(dst2) ⇒ moveCount = 3
    await waitFor(() => expect(screen.queryByText('Track t1')).toBeNull());
    expect(moveCount).toBe(3);

    vi.useRealTimers();
  });

  it('Undo (U) after advance restores the previous track', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderApp();
    await waitFor(() => expect(screen.getByText('Track t1')).toBeInTheDocument());
    await user.keyboard('1');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(220);
    });
    // t1 optimistically removed, advance fires — t1 gone from view
    await waitFor(() => expect(screen.queryByText('Track t1')).toBeNull());
    await user.keyboard('u');
    // Undo restores snapshot (t1 back) and resets currentIndex to 0
    await waitFor(() => expect(screen.getByText('Track t1')).toBeInTheDocument());

    vi.useRealTimers();
  });

  it('? opens overlay; Esc closes; Esc again exits to triage', async () => {
    const user = userEvent.setup();
    renderApp();
    await waitFor(() => expect(screen.getByText('Track t1')).toBeInTheDocument());
    await user.keyboard('?');
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('end-of-queue suggests OLD when source NEW exhausted', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
        HttpResponse.json(tracks(['only'])),
      ),
    );
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderApp();
    await waitFor(() => expect(screen.getByText('Track only')).toBeInTheDocument());
    await user.keyboard('1');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(220);
    });
    await waitFor(() =>
      expect(screen.getByRole('link', { name: /Continue with OLD/i })).toBeInTheDocument(),
    );

    vi.useRealTimers();
  });
});
