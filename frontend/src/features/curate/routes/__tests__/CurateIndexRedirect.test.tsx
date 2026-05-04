import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { CurateIndexRedirect } from '../CurateIndexRedirect';
import { LAST_CURATE_STYLE_KEY } from '../../lib/lastCurateLocation';

function client() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

beforeEach(() => {
  tokenStore.set('TOK');
  localStorage.clear();
});

function wrap() {
  const qc = client();
  return (
    <MemoryRouter initialEntries={['/curate']}>
      <QueryClientProvider client={qc}>
        <MantineProvider theme={testTheme}>
          <Routes>
            <Route path="/curate" element={<CurateIndexRedirect />} />
            <Route
              path="/curate/:styleId"
              element={<div data-testid="style-route">styleRoute</div>}
            />
            <Route path="/categories" element={<div data-testid="categories-route">cat</div>} />
          </Routes>
        </MantineProvider>
      </QueryClientProvider>
    </MemoryRouter>
  );
}

describe('CurateIndexRedirect', () => {
  it('redirects to lastCurateStyle when present and style exists', async () => {
    localStorage.setItem(LAST_CURATE_STYLE_KEY, 's7');
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [
            { id: 's1', name: 'House' },
            { id: 's7', name: 'Tech House' },
          ],
          total: 2,
          limit: 200,
          offset: 0,
        }),
      ),
    );
    render(wrap());
    await waitFor(() =>
      expect(screen.getByTestId('style-route')).toBeInTheDocument(),
    );
  });

  it('falls back to first style when lastCurateStyle missing', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [{ id: 'first', name: 'House' }],
          total: 1,
          limit: 200,
          offset: 0,
        }),
      ),
    );
    render(wrap());
    await waitFor(() =>
      expect(screen.getByTestId('style-route')).toBeInTheDocument(),
    );
  });

  it('redirects to /categories when no styles exist', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
    render(wrap());
    await waitFor(() =>
      expect(screen.getByTestId('categories-route')).toBeInTheDocument(),
    );
  });
});
