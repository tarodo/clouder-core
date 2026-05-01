import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { CategoryDetailPage } from '../CategoryDetailPage';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider>
      <ModalsProvider>
        <Notifications />
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={['/categories/s1/c1']}>
            <Routes>
              <Route path="/categories/:styleId/:id" element={children} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

beforeEach(() => {
  tokenStore.set('TOK');
  server.use(
    http.get('http://localhost/categories/c1', () =>
      HttpResponse.json({
        id: 'c1',
        style_id: 's1',
        style_name: 'House',
        name: 'Deep',
        position: 0,
        track_count: 0,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
    http.get('http://localhost/categories/c1/tracks', () =>
      HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
    ),
  );
});

describe('CategoryDetailPage', () => {
  it('renders header and empty tracks state', async () => {
    render(
      <Wrapper>
        <CategoryDetailPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Deep')).toBeInTheDocument());
    expect(screen.getByText(/no tracks yet/i)).toBeInTheDocument();
  });

  it('shows not-found on 404', async () => {
    server.use(
      http.get('http://localhost/categories/c1', () =>
        HttpResponse.json(
          { error_code: 'category_not_found', message: 'gone', correlation_id: 'c' },
          { status: 404 },
        ),
      ),
    );
    render(
      <Wrapper>
        <CategoryDetailPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText(/not found/i)).toBeInTheDocument());
  });
});
