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
  it('removes run from tracker on terminal status', async () => {
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
      expect(runsTrackerStore.getState().runs.has('r1')).toBe(false),
    );
  });
});
