import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/setup';
import { tokenStore } from '../../../auth/tokenStore';
import { PlaylistsListPage } from '../routes/PlaylistsListPage';
import { testTheme } from '../../../test/theme';

function Wrapper({ children, entries }: { children: React.ReactNode; entries: string[] }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider theme={testTheme}>
      <ModalsProvider>
        <Notifications />
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={entries}>
            <Routes>
              <Route path="/playlists" element={children} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

beforeEach(() => {
  tokenStore.set('TOK');
});

describe('Playlists integration smoke', () => {
  it('shows the empty list, opens create dialog, posts a new playlist', async () => {
    const user = userEvent.setup();
    let posted: { name: string } | null = null;
    server.use(
      http.get('http://localhost/playlists', () =>
        HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 }),
      ),
      http.post('http://localhost/playlists', async ({ request }) => {
        posted = (await request.json()) as { name: string };
        return HttpResponse.json(
          {
            id: 'p1',
            user_id: 'u1',
            name: posted.name,
            description: null,
            is_public: false,
            cover_s3_key: null,
            cover_url: null,
            cover_uploaded_at: null,
            spotify_playlist_id: null,
            last_published_at: null,
            needs_republish: false,
            track_count: 0,
            created_at: '2026-05-12T00:00:00Z',
            updated_at: '2026-05-12T00:00:00Z',
          },
          { status: 201 },
        );
      }),
    );

    render(
      <Wrapper entries={['/playlists']}>
        <PlaylistsListPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText(/No playlists yet/i)).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Create playlist/i }));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByLabelText('Name'), 'Sunday house');
    await user.click(within(dialog).getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(posted?.name).toBe('Sunday house'));
  });
});
