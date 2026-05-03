import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications, notifications } from '@mantine/notifications';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/setup';
import { tokenStore } from '../../../auth/tokenStore';
import '../../../i18n';
import { TriageDetailPage } from '../routes/TriageDetailPage';

function renderAt(path: string) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  const router = createMemoryRouter(
    [
      { path: '/triage/:styleId/:id', element: <TriageDetailPage /> },
      { path: '/triage/:styleId', element: <div data-testid="list-page" /> },
    ],
    { initialEntries: [path] },
  );
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <ModalsProvider>
          <Notifications position="top-right" />
          <RouterProvider router={router} />
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const inProgressBlock = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'W17',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS',
  created_at: '2026-04-21T08:00:00Z',
  updated_at: '2026-04-21T08:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'bk1', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 5 },
    { id: 'bk2', bucket_type: 'OLD', category_id: null, category_name: null, inactive: false, track_count: 0 },
    { id: 'bk3', bucket_type: 'NOT', category_id: null, category_name: null, inactive: false, track_count: 0 },
    { id: 'bk4', bucket_type: 'DISCARD', category_id: null, category_name: null, inactive: false, track_count: 0 },
    { id: 'bk5', bucket_type: 'UNCLASSIFIED', category_id: null, category_name: null, inactive: false, track_count: 0 },
    { id: 'bk6', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Tech', inactive: false, track_count: 2 },
    { id: 'bk7', bucket_type: 'STAGING', category_id: 'c2', category_name: 'Old', inactive: true, track_count: 1 },
  ],
};

describe('TriageDetailPage integration', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    notifications.clean();
  });
  afterEach(() => notifications.clean());

  it('renders header + bucket grid (5 tech + 2 STAGING)', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
    );
    renderAt('/triage/s1/b1');
    expect(await screen.findByText('W17')).toBeInTheDocument();
    const links = await screen.findAllByRole('link');
    // back link + 7 bucket cards. Filter to bucket links to make the count robust.
    expect(links.filter((l) => l.getAttribute('href')?.includes('/buckets/'))).toHaveLength(7);
  });

  it('soft-deletes from kebab + navigates back + green toast', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
      http.delete('http://localhost/triage/blocks/b1', () => new HttpResponse(null, { status: 204 })),
    );
    renderAt('/triage/s1/b1');
    await screen.findByText('W17');
    await userEvent.click(screen.getByRole('button', { name: /Delete block/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Delete block/ }));
    // Confirm modal
    await userEvent.click(await screen.findByRole('button', { name: /^Delete$/ }));
    await waitFor(() => expect(screen.getByTestId('list-page')).toBeInTheDocument());
    expect(await screen.findByText(/Triage block deleted/)).toBeInTheDocument();
  });

  it('FINALIZED variant hides Finalize button + kebab', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () =>
        HttpResponse.json({
          ...inProgressBlock,
          status: 'FINALIZED',
          finalized_at: '2026-04-22T10:00:00Z',
        }),
      ),
    );
    renderAt('/triage/s1/b1');
    await screen.findByText('FINALIZED');
    expect(screen.queryByRole('button', { name: /Finalize/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Delete block/ })).not.toBeInTheDocument();
  });

  it('404 shows block-not-found + back link', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/missing', () =>
        HttpResponse.json(
          { error_code: 'triage_block_not_found', message: 'no' },
          { status: 404 },
        ),
      ),
    );
    renderAt('/triage/s1/missing');
    expect(await screen.findByText(/Block not found/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Back to triage/ })).toHaveAttribute(
      'href',
      '/triage/s1',
    );
  });

  it('inactive STAGING is dimmed (opacity 0.5) but still clickable', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
    );
    renderAt('/triage/s1/b1');
    const links = await screen.findAllByRole('link');
    const stagingInactiveLink = links.find((l) =>
      l.getAttribute('href')?.endsWith('/buckets/bk7'),
    )!;
    expect(stagingInactiveLink).toHaveStyle('opacity: 0.5');
  });
});

describe('TriageDetailPage Finalize modal', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    notifications.clean();
  });
  afterEach(() => notifications.clean());

  it('opens FinalizeModal when Finalize button is clicked', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
    );
    const user = userEvent.setup();
    renderAt('/triage/s1/b1');
    await user.click(await screen.findByRole('button', { name: 'Finalize' }));
    await waitFor(() => {
      const titleA = screen.queryByText(/Finalize W17\?/i);
      const titleB = screen.queryByText('Cannot finalize yet');
      expect(titleA || titleB).toBeTruthy();
    });
  });
});
