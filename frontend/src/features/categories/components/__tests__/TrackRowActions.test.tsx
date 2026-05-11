import React from 'react';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications, notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { TrackRowActions } from '../TrackRowActions';
import type { CategoryTrack } from '../../hooks/useCategoryTracks';
import { testTheme } from '../../../../test/theme';
import '../../../../i18n';

const TRACK: CategoryTrack = {
  id: 't1',
  title: 'Lift Off',
  mix_name: null,
  artists: [],
  label: null,
  bpm: null,
  length_ms: null,
  publish_date: null,
  spotify_release_date: null,
  isrc: null,
  spotify_id: null,
  release_type: null,
  is_ai_suspected: false,
  added_at: '2026-01-01T00:00:00Z',
  source_triage_block_id: null,
  tags: [],
};

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
  return (
    <MantineProvider theme={testTheme}>
      <Notifications />
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </MantineProvider>
  );
}

function categoriesPayload(items: Array<{ id: string; name: string }>) {
  return {
    items: items.map((c, i) => ({
      id: c.id,
      style_id: 's1',
      style_name: 'House',
      name: c.name,
      position: i,
      track_count: 0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    })),
    total: items.length,
    limit: 200,
    offset: 0,
  };
}

describe('TrackRowActions', () => {
  beforeEach(() => tokenStore.set('TOK'));
  afterEach(() => notifications.clean());

  it('opens the menu and lists categories with current disabled', async () => {
    server.use(
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json(
          categoriesPayload([
            { id: 'c1', name: 'Energetic' },
            { id: 'c2', name: 'Deep' },
            { id: 'c3', name: 'Sunset' },
          ]),
        ),
      ),
    );
    render(
      <Wrapper>
        <TrackRowActions track={TRACK} currentCategoryId="c1" styleId="s1" />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /Track actions/i }));
    const menu = await screen.findByRole('menu');
    expect(within(menu).getByText('Move to')).toBeInTheDocument();
    expect(within(menu).getByText('Deep')).toBeInTheDocument();
    expect(within(menu).getByText('Sunset')).toBeInTheDocument();
    expect(within(menu).getByText(/Energetic.*current/i)).toBeInTheDocument();
    expect(within(menu).getByRole('menuitem', { name: /Energetic/ })).toHaveAttribute(
      'data-disabled',
      'true',
    );
    expect(within(menu).getByRole('menuitem', { name: /Remove from category/ })).toBeInTheDocument();
  });

  it('shows "No other categories" when only the current category exists', async () => {
    server.use(
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json(categoriesPayload([{ id: 'c1', name: 'Only' }])),
      ),
    );
    render(
      <Wrapper>
        <TrackRowActions track={TRACK} currentCategoryId="c1" styleId="s1" />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /Track actions/i }));
    const menu = await screen.findByRole('menu');
    expect(within(menu).getByText(/No other categories/)).toBeInTheDocument();
  });

  it('move click triggers POST then DELETE and shows success toast with Undo', async () => {
    let postHit = false;
    let deleteHit = false;
    server.use(
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json(
          categoriesPayload([
            { id: 'c1', name: 'Energetic' },
            { id: 'c2', name: 'Deep' },
          ]),
        ),
      ),
      http.post('http://localhost/categories/c2/tracks', () => {
        postHit = true;
        return HttpResponse.json({ ok: true });
      }),
      http.delete('http://localhost/categories/c1/tracks/t1', () => {
        deleteHit = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(
      <Wrapper>
        <TrackRowActions track={TRACK} currentCategoryId="c1" styleId="s1" />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /Track actions/i }));
    const menu = await screen.findByRole('menu');
    await userEvent.click(within(menu).getByRole('menuitem', { name: /Deep/ }));
    await waitFor(() => expect(postHit).toBe(true));
    await waitFor(() => expect(deleteHit).toBe(true));
    expect(await screen.findByText(/Moved to Deep/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Undo/ })).toBeInTheDocument();
  });

  it('remove click triggers DELETE and shows success toast with Undo', async () => {
    let deleteHit = false;
    server.use(
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json(categoriesPayload([{ id: 'c1', name: 'Energetic' }])),
      ),
      http.delete('http://localhost/categories/c1/tracks/t1', () => {
        deleteHit = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(
      <Wrapper>
        <TrackRowActions track={TRACK} currentCategoryId="c1" styleId="s1" />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /Track actions/i }));
    const menu = await screen.findByRole('menu');
    await userEvent.click(within(menu).getByRole('menuitem', { name: /Remove from category/ }));
    await waitFor(() => expect(deleteHit).toBe(true));
    expect(await screen.findByText(/Removed from category/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Undo/ })).toBeInTheDocument();
  });
});
