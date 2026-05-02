import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { ModalsProvider } from '@mantine/modals';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { TriageBlocksList } from '../TriageBlocksList';

const server = setupServer();
beforeEach(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  server.close();
});

const sampleBlock = (overrides = {}) => ({
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'B1',
  date_from: '2026-04-20',
  date_to: '2026-04-26',
  status: 'IN_PROGRESS',
  created_at: '2026-04-20T10:00:00Z',
  updated_at: '2026-04-20T10:00:00Z',
  finalized_at: null,
  track_count: 5,
  ...overrides,
});

function renderList() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  return render(
    <MemoryRouter>
      <MantineProvider>
        <QueryClientProvider client={qc}>
          <ModalsProvider>
            <Notifications />
            <TriageBlocksList styleId="s1" />
          </ModalsProvider>
        </QueryClientProvider>
      </MantineProvider>
    </MemoryRouter>,
  );
}

describe('TriageBlocksList', () => {
  it('renders Active tab with results and counter', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        const status = new URL(request.url).searchParams.get('status');
        if (status === 'IN_PROGRESS' || status === null) {
          return HttpResponse.json({
            items: [sampleBlock()],
            total: 1,
            limit: 50,
            offset: 0,
          });
        }
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );

    renderList();
    expect(await screen.findByText('B1')).toBeInTheDocument();
    expect(await screen.findByRole('tab', { name: /Active.*1/ })).toBeInTheDocument();
    expect(await screen.findByRole('tab', { name: /Finalized.*0/ })).toBeInTheDocument();
    expect(await screen.findByRole('tab', { name: /All.*1/ })).toBeInTheDocument();
  });

  it('switches tabs', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        const status = new URL(request.url).searchParams.get('status');
        if (status === 'FINALIZED') {
          return HttpResponse.json({
            items: [sampleBlock({ id: 'fb', name: 'Finalized B', status: 'FINALIZED', finalized_at: '2026-04-26T18:00:00Z' })],
            total: 1,
            limit: 50,
            offset: 0,
          });
        }
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );

    renderList();
    await userEvent.click(await screen.findByRole('tab', { name: /Finalized/ }));
    expect(await screen.findByText('Finalized B')).toBeInTheDocument();
  });

  it('renders empty state for Active tab when zero results', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );

    renderList();
    expect(await screen.findByText(/No active triage blocks/i)).toBeInTheDocument();
  });

  it('shows load-more button when total > shown', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset'));
        if (offset === 0) {
          return HttpResponse.json({
            items: Array.from({ length: 50 }, (_, i) => sampleBlock({ id: `a${i}`, name: `B${i}` })),
            total: 60,
            limit: 50,
            offset: 0,
          });
        }
        return HttpResponse.json({
          items: Array.from({ length: 10 }, (_, i) => sampleBlock({ id: `b${i}`, name: `C${i}` })),
          total: 60,
          limit: 50,
          offset: 50,
        });
      }),
    );

    renderList();
    const button = await screen.findByRole('button', { name: /Show more/i });
    await userEvent.click(button);
    expect(await screen.findByText('C0')).toBeInTheDocument();
  });
});
