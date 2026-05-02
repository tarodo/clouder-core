import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { writeLastVisitedStyle } from '../../lib/lastVisitedStyle';
import { CategoriesIndexRedirect } from '../CategoriesIndexRedirect';

function Wrapper({ initialEntries }: { initialEntries: string[] }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={initialEntries}>
          <Routes>
            <Route path="/categories" element={<CategoriesIndexRedirect />} />
            <Route path="/categories/:styleId" element={<div data-testid="landed">landed</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>
  );
}

describe('CategoriesIndexRedirect', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    localStorage.clear();
  });

  it('redirects to first style when nothing stored', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [
            { id: 's-first', name: 'House' },
            { id: 's-other', name: 'Tech House' },
          ],
          total: 2,
          limit: 200,
          offset: 0,
        }),
      ),
    );
    render(<Wrapper initialEntries={['/categories']} />);
    await waitFor(() => expect(screen.getByTestId('landed')).toBeInTheDocument());
  });

  it('uses stored style id when present', async () => {
    writeLastVisitedStyle('s-other');
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [
            { id: 's-first', name: 'House' },
            { id: 's-other', name: 'Tech House' },
          ],
          total: 2,
          limit: 200,
          offset: 0,
        }),
      ),
    );
    render(<Wrapper initialEntries={['/categories']} />);
    await waitFor(() => expect(screen.getByTestId('landed')).toBeInTheDocument());
  });

  it('shows no-styles state when list empty', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
    render(<Wrapper initialEntries={['/categories']} />);
    await waitFor(() => expect(screen.getByText(/no styles available/i)).toBeInTheDocument());
  });
});
