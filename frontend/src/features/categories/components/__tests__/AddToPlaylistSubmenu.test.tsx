import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider, Menu } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { AddToPlaylistSubmenu } from '../AddToPlaylistSubmenu';
import { testTheme } from '../../../../test/theme';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider theme={testTheme}>
      <Notifications />
      <QueryClientProvider client={qc}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>
  );
}

const seedPlaylists = {
  items: [
    {
      id: 'p1',
      user_id: 'u1',
      name: 'Hot New',
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
  ],
  total: 1,
  limit: 100,
  offset: 0,
};

beforeEach(() => {
  tokenStore.set('TOK');
  server.use(
    http.get('http://localhost/playlists', () => HttpResponse.json(seedPlaylists)),
  );
});

describe('AddToPlaylistSubmenu', () => {
  it('lists user playlists inside an open Menu', async () => {
    render(
      <Wrapper>
        <Menu>
          <Menu.Target>
            <button>open</button>
          </Menu.Target>
          <Menu.Dropdown>
            <AddToPlaylistSubmenu trackId="t1" />
          </Menu.Dropdown>
        </Menu>
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'open' }));
    const menu = await screen.findByRole('menu');
    await waitFor(() => expect(within(menu).getByText('Hot New')).toBeInTheDocument());
  });

  it('posts to /playlists/p1/tracks when an item is clicked', async () => {
    let posted: { track_ids: string[] } | null = null;
    server.use(
      http.post('http://localhost/playlists/p1/tracks', async ({ request }) => {
        posted = (await request.json()) as { track_ids: string[] };
        return HttpResponse.json(
          { added: ['t1'], skipped_duplicates: [], position_after: 1 },
          { status: 201 },
        );
      }),
    );
    render(
      <Wrapper>
        <Menu>
          <Menu.Target>
            <button>open</button>
          </Menu.Target>
          <Menu.Dropdown>
            <AddToPlaylistSubmenu trackId="t1" />
          </Menu.Dropdown>
        </Menu>
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'open' }));
    const menu = await screen.findByRole('menu');
    await userEvent.click(await within(menu).findByText('Hot New'));
    await waitFor(() => expect(posted).toEqual({ track_ids: ['t1'] }));
  });
});
