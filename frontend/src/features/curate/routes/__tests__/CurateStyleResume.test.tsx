import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { CurateStyleResume } from '../CurateStyleResume';
import {
  LAST_CURATE_LOCATION_KEY,
} from '../../lib/lastCurateLocation';

function client() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

const wrap = (initial: string, target = '/session/:styleId/:blockId/:bucketId') => {
  const qc = client();
  return (
    <MemoryRouter initialEntries={[initial]}>
      <QueryClientProvider client={qc}>
        <MantineProvider theme={testTheme}>
          <Routes>
            <Route path="/curate/:styleId" element={<CurateStyleResume />} />
            <Route path={target} element={<div data-testid="session-loaded" />} />
          </Routes>
        </MantineProvider>
      </QueryClientProvider>
    </MemoryRouter>
  );
};

beforeEach(() => {
  tokenStore.set('TOK');
  localStorage.clear();
});

const inProgressBlock = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'W17',
  date_from: '2026-04-21',
  date_to: '2026-04-27',
  status: 'IN_PROGRESS',
  created_at: '2026-04-20T00:00:00Z',
  updated_at: '2026-04-20T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'src', bucket_type: 'NEW', inactive: false, track_count: 5 },
  ],
};

describe('CurateStyleResume', () => {
  it('redirects to session route on healthy resume entry', async () => {
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({ s1: { blockId: 'b1', bucketId: 'src', updatedAt: 'x' } }),
    );
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
    );
    render(wrap('/curate/s1', '/curate/:styleId/:blockId/:bucketId'));
    await waitFor(() => expect(screen.getByTestId('session-loaded')).toBeInTheDocument());
  });

  it('renders setup picker when no resume entry exists', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json([{ id: 's1', name: 'House' }]),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    render(wrap('/curate/s1'));
    await waitFor(() =>
      expect(screen.getByText(/No active blocks/i)).toBeInTheDocument(),
    );
  });

  it('cleans up + renders setup picker when stored block is FINALIZED', async () => {
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({ s1: { blockId: 'b1', bucketId: 'src', updatedAt: 'x' } }),
    );
    server.use(
      http.get('http://localhost/triage/blocks/b1', () =>
        HttpResponse.json({ ...inProgressBlock, status: 'FINALIZED' }),
      ),
      http.get('http://localhost/styles', () =>
        HttpResponse.json([{ id: 's1', name: 'House' }]),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    render(wrap('/curate/s1'));
    await waitFor(() =>
      expect(screen.getByText(/No active blocks/i)).toBeInTheDocument(),
    );
    expect(localStorage.getItem(LAST_CURATE_LOCATION_KEY)).not.toContain('"s1"');
  });
});
