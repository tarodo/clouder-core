import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { CategoriesListPage } from '../CategoriesListPage';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider>
      <ModalsProvider>
        <Notifications />
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={['/categories/s1']}>
            <Routes>
              <Route path="/categories/:styleId" element={children} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

const seed = [
  {
    id: 'c1',
    style_id: 's1',
    style_name: 'House',
    name: 'Deep',
    position: 0,
    track_count: 3,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
];

beforeEach(() => {
  tokenStore.set('TOK');
  server.use(
    http.get('http://localhost/styles', () =>
      HttpResponse.json({ items: [{ id: 's1', name: 'House' }], total: 1, limit: 200, offset: 0 }),
    ),
    http.get('http://localhost/styles/s1/categories', () =>
      HttpResponse.json({ items: seed, total: 1, limit: 200, offset: 0 }),
    ),
  );
});

describe('CategoriesListPage', () => {
  it('renders category rows', async () => {
    render(
      <Wrapper>
        <CategoriesListPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Deep')).toBeInTheDocument());
  });

  it('opens create dialog and posts new category', async () => {
    server.use(
      http.post('http://localhost/styles/s1/categories', async () =>
        HttpResponse.json(
          {
            id: 'c2',
            style_id: 's1',
            style_name: 'House',
            name: 'New',
            position: 1,
            track_count: 0,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
          { status: 201 },
        ),
      ),
    );
    render(
      <Wrapper>
        <CategoriesListPage />
      </Wrapper>,
    );
    await userEvent.click(await screen.findByRole('button', { name: /create category/i }));
    await userEvent.type(screen.getByRole('textbox', { name: /name/i }), 'New');
    await userEvent.click(screen.getByRole('button', { name: /^create$/i }));
    await waitFor(() => expect(screen.queryByRole('button', { name: /^create$/i })).not.toBeInTheDocument());
  });

  it('shows empty state when no categories', async () => {
    server.use(
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <CategoriesListPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText(/no categories yet/i)).toBeInTheDocument());
  });
});
