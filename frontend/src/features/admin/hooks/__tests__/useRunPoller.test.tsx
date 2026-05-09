import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';
import type { ReactNode } from 'react';
import { server } from '../../../../test/setup';
import { useRunPoller } from '../useRunPoller';
import { runsTrackerStore } from '../../lib/runsTracker';

afterEach(() => {
  runsTrackerStore.getState().clear();
});

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { gcTime: Infinity, retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useRunPoller', () => {
  it('sets terminalStatus on the tracker when run reaches a terminal state', async () => {
    runsTrackerStore.getState().add({
      run_id: 'r1',
      styleId: 1,
      weekYear: 2026,
      weekNumber: 5,
      startedAt: 0,
    });
    server.use(
      http.get('http://localhost/runs/r1', () =>
        HttpResponse.json({ run_id: 'r1', status: 'completed' }),
      ),
    );

    renderHook(
      () => useRunPoller('r1', { styleId: 1, weekYear: 2026, weekNumber: 5 }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() =>
      expect(runsTrackerStore.getState().runs.get('r1')?.terminalStatus).toBe('completed'),
    );
    // Run is still in tracker — RunProgressToast is responsible for removal.
    expect(runsTrackerStore.getState().runs.has('r1')).toBe(true);
  });

  it('sets terminalStatus=failed when run fails', async () => {
    runsTrackerStore.getState().add({
      run_id: 'r2',
      styleId: 2,
      weekYear: 2026,
      weekNumber: 6,
      startedAt: 0,
    });
    server.use(
      http.get('http://localhost/runs/r2', () =>
        HttpResponse.json({ run_id: 'r2', status: 'failed' }),
      ),
    );

    renderHook(
      () => useRunPoller('r2', { styleId: 2, weekYear: 2026, weekNumber: 6 }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() =>
      expect(runsTrackerStore.getState().runs.get('r2')?.terminalStatus).toBe('failed'),
    );
  });
});
