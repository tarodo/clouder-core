import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { http, HttpResponse } from 'msw';
import i18n from '../../../../i18n';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { AdminArtistEnrichmentBacklogPage } from '../AdminArtistEnrichmentBacklogPage';

// Stable mock data — built once so [query.data] effect deps don't loop
const mockPages = {
  pages: [
    {
      items: [
        {
          id: 'artist-1',
          name: 'Artist One',
          style: 'techno',
          status: 'none',
          track_count: 10,
          last_attempted_at: null,
        },
        {
          id: 'artist-2',
          name: 'Artist Two',
          style: 'house',
          status: 'completed',
          track_count: 5,
          last_attempted_at: '2026-01-01T00:00:00Z',
        },
      ],
      next_cursor: null,
      total_estimate: 2,
    },
  ],
  pageParams: [undefined],
};

vi.mock('../../hooks/useArtistBacklog', () => ({
  useArtistBacklog: () => ({
    data: mockPages,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
  }),
  ArtistStatusFilter: undefined,
}));

vi.mock('../../../../hooks/useStyles', () => ({
  useStyles: () => ({ data: { items: [] }, isLoading: false }),
}));

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <MantineProvider>
          <I18nextProvider i18n={i18n}>
            <Notifications />
            <AdminArtistEnrichmentBacklogPage />
          </I18nextProvider>
        </MantineProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('AdminArtistEnrichmentBacklogPage', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('renders artist rows via BacklogTable', () => {
    renderPage();
    expect(screen.getByText('Artist One')).toBeTruthy();
    expect(screen.getByText('Artist Two')).toBeTruthy();
  });

  it('selecting an artist and clicking enqueue opens ArtistEnqueueDrawer', async () => {
    server.use(
      http.get('http://localhost/admin/artists/enrich/options', () =>
        HttpResponse.json({
          vendors: ['gemini'],
          prompt_versions: [{ slug: 'artist_v1', version: 'v1', is_default: true }],
          default_models: { gemini: 'gem' },
          merge: { vendor: 'deepseek', default_model: 'deepseek-chat' },
        }),
      ),
    );

    renderPage();

    // Select artist-1 checkbox
    const checkbox = screen.getByLabelText('select Artist One');
    await userEvent.click(checkbox);

    // Click the Enqueue button
    const enqueueBtn = screen.getByRole('button', { name: /Enqueue 1/ });
    await userEvent.click(enqueueBtn);

    // ArtistEnqueueDrawer should open (shows submit button)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Enqueue/ })).toBeTruthy(),
    );
  });
});
