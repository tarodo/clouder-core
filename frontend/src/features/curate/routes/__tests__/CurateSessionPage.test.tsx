import React from 'react';
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { CurateSessionPage } from '../CurateSessionPage';

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

describe('CurateSessionPage', () => {
  it('mounts accent-magenta on body and removes on unmount', async () => {
    tokenStore.set('TOK');
    server.use(
      http.get('http://localhost/triage/blocks/b1', () =>
        HttpResponse.json({
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
          buckets: [{ id: 'src', bucket_type: 'NEW', inactive: false, track_count: 0 }],
        }),
      ),
      http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    const qc = makeClient();
    const { unmount } = render(
      <MemoryRouter initialEntries={['/curate/s1/b1/src']}>
        <QueryClientProvider client={qc}>
          <MantineProvider theme={testTheme}>
            <Routes>
              <Route path="/curate/:styleId/:blockId/:bucketId" element={<CurateSessionPage />} />
            </Routes>
          </MantineProvider>
        </QueryClientProvider>
      </MemoryRouter>,
    );
    expect(document.body.classList.contains('accent-magenta')).toBe(true);
    unmount();
    expect(document.body.classList.contains('accent-magenta')).toBe(false);
  });
});
