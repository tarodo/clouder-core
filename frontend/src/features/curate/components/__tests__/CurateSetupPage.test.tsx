import React from 'react';
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { CurateSetupPage } from '../CurateSetupPage';

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

const wrap = (ui: React.ReactElement) => {
  const qc = makeClient();
  return (
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <MantineProvider theme={testTheme}>{ui}</MantineProvider>
      </QueryClientProvider>
    </MemoryRouter>
  );
};

beforeEach(() => tokenStore.set('TOK'));

describe('CurateSetupPage', () => {
  it('shows the no-active-blocks empty state when style has zero IN_PROGRESS blocks', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({ items: [{ id: 's1', name: 'Tech House' }], total: 1, limit: 200, offset: 0 }),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    render(wrap(<CurateSetupPage styleId="s1" />));
    expect(
      await screen.findByText(/No active blocks for Tech House/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Triage/i })).toHaveAttribute(
      'href',
      '/triage/s1',
    );
  });

  it('lists IN_PROGRESS blocks and pre-selects first; bucket select pre-selects NEW', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({ items: [{ id: 's1', name: 'Tech House' }], total: 1, limit: 200, offset: 0 }),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [
            {
              id: 'b1',
              style_id: 's1',
              style_name: 'Tech House',
              name: 'W17',
              date_from: '2026-04-21',
              date_to: '2026-04-27',
              status: 'IN_PROGRESS',
              created_at: '2026-04-20T00:00:00Z',
              updated_at: '2026-04-20T00:00:00Z',
              finalized_at: null,
              total_tracks: 100,
              track_count_by_bucket: {},
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      ),
      http.get('http://localhost/triage/blocks/b1', () =>
        HttpResponse.json({
          id: 'b1',
          style_id: 's1',
          style_name: 'Tech House',
          name: 'W17',
          date_from: '2026-04-21',
          date_to: '2026-04-27',
          status: 'IN_PROGRESS',
          created_at: '2026-04-20T00:00:00Z',
          updated_at: '2026-04-20T00:00:00Z',
          finalized_at: null,
          buckets: [
            { id: 'b-new', bucket_type: 'NEW', inactive: false, track_count: 5 },
            { id: 'b-old', bucket_type: 'OLD', inactive: false, track_count: 0 },
            { id: 'b-stage', bucket_type: 'STAGING', inactive: false, track_count: 0,
              category_id: 'c1', category_name: 'Big Room' },
          ],
        }),
      ),
    );
    render(wrap(<CurateSetupPage styleId="s1" />));
    await waitFor(() =>
      expect(screen.getByRole('link', { name: /Start curating/i })).toHaveAttribute(
        'href',
        '/curate/s1/b1/b-new',
      ),
    );
  });
});
