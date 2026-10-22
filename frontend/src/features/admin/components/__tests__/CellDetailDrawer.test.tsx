import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { server } from '../../../../test/setup';
import { CellDetailDrawer } from '../CellDetailDrawer';

function ui(props: React.ComponentProps<typeof CellDetailDrawer>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <CellDetailDrawer {...props} />
      </MantineProvider>
    </QueryClientProvider>
  );
}

describe('CellDetailDrawer', () => {
  it('renders ingest form on empty', async () => {
    server.use(
      http.get('http://localhost/admin/runs', () =>
        HttpResponse.json({ items: [] }),
      ),
    );
    render(
      ui({
        open: true,
        onClose: vi.fn(),
        styleId: 1,
        styleName: 'Tech',
        weekYear: 2026,
        weekNumber: 5,
        state: 'empty',
        cell: null,
      }),
    );
    const dialog = await screen.findByRole('dialog');
    expect(
      within(dialog).getByRole('button', { name: 'Start ingest' }),
    ).toBeInTheDocument();
  });

  it('renders run details on loaded', async () => {
    server.use(
      http.get('http://localhost/admin/runs', () =>
        HttpResponse.json({ items: [] }),
      ),
    );
    render(
      ui({
        open: true,
        onClose: vi.fn(),
        styleId: 1,
        styleName: 'Tech',
        weekYear: 2026,
        weekNumber: 5,
        state: 'loaded',
        cell: {
          week_number: 5,
          status: 'completed',
          run_id: 'r',
          item_count: 42,
          is_custom_range: false,
          period_start: '2026-01-31',
          period_end: '2026-02-06',
          started_at: '2026-02-07T00:00:00Z',
          finished_at: '2026-02-07T00:01:00Z',
        },
      }),
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('2026-01-31 – 2026-02-06')).toBeInTheDocument();
    expect(
      within(dialog).getByRole('button', { name: 'Re-ingest' }),
    ).toBeInTheDocument();
  });

  it('links to the YouTube review of the week when tracks wait for it', async () => {
    server.use(http.get('http://localhost/admin/runs', () => HttpResponse.json({ items: [] })));
    render(
      <MemoryRouter>
        {ui({
          open: true,
          onClose: vi.fn(),
          styleId: 90,
          styleName: 'Tech House',
          weekYear: 2026,
          weekNumber: 40,
          state: 'empty',
          cell: null,
          youtubeReview: 55,
        })}
      </MemoryRouter>,
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('YouTube: 55 tracks to review')).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: 'Review these tracks' })).toHaveAttribute(
      'href', '/admin/youtube-review?style=90&year=2026&week=40',
    );
  });

  it('shows no YouTube review link when nothing waits', async () => {
    server.use(http.get('http://localhost/admin/runs', () => HttpResponse.json({ items: [] })));
    render(
      ui({
        open: true, onClose: vi.fn(), styleId: 90, styleName: 'Tech House', weekYear: 2026,
        weekNumber: 40, state: 'empty', cell: null, youtubeReview: 0,
      }),
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).queryByRole('link', { name: 'Review these tracks' })).toBeNull();
  });
});
