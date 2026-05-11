import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/setup';
import { tokenStore } from '../../../auth/tokenStore';
import { testTheme } from '../../../test/theme';
import { TracksTab } from '../../categories/components/TracksTab';

function W({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <MantineProvider theme={testTheme}>
      <ModalsProvider>
        <Notifications />
        <QueryClientProvider client={qc}>
          <MemoryRouter>{children}</MemoryRouter>
        </QueryClientProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

describe('Track-tags end-to-end', () => {
  beforeEach(() => {
    tokenStore.set('TOK');

    // In-memory tag store for the test
    let tags: any[] = [];
    let trackTags: any[] = [];

    server.use(
      http.get('http://localhost/styles/:styleId/categories', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
      http.get('http://localhost/tags', () =>
        HttpResponse.json({ items: tags, total: tags.length, limit: 200, offset: 0 }),
      ),
      http.post('http://localhost/tags', async ({ request }) => {
        const body = (await request.json()) as { name: string; color: string | null };
        const tag = {
          id: `tg-${tags.length + 1}`,
          name: body.name,
          color: body.color,
          created_at: '2026-05-11T00:00:00Z', updated_at: '2026-05-11T00:00:00Z',
        };
        tags.push(tag);
        return HttpResponse.json(tag, { status: 201 });
      }),
      http.delete('http://localhost/tags/:id', ({ params }) => {
        tags = tags.filter((t) => t.id !== params.id);
        trackTags = trackTags.filter((t) => t.tag_id !== params.id);
        return new HttpResponse(null, { status: 204 });
      }),
      http.post('http://localhost/tracks/:trackId/tags', async ({ params, request }) => {
        const body = (await request.json()) as { tag_id: string };
        if (!trackTags.some((t) => t.track_id === params.trackId && t.tag_id === body.tag_id)) {
          trackTags.push({ track_id: params.trackId, tag_id: body.tag_id });
        }
        return HttpResponse.json({ tags: [] }, { status: 201 });
      }),
      http.delete('http://localhost/tracks/:trackId/tags/:tagId', ({ params }) => {
        trackTags = trackTags.filter(
          (t) => !(t.track_id === params.trackId && t.tag_id === params.tagId),
        );
        return new HttpResponse(null, { status: 204 });
      }),
      http.get('http://localhost/categories/c1/tracks', ({ request }) => {
        const url = new URL(request.url);
        const tagFilter = (url.searchParams.get('tags') ?? '').split(',').filter(Boolean);
        const match = url.searchParams.get('match') === 'any' ? 'any' : 'all';
        const trackTagIds = trackTags
          .filter((t) => t.track_id === 't1')
          .map((t) => t.tag_id);
        let include = true;
        if (tagFilter.length) {
          include = match === 'all'
            ? tagFilter.every((id) => trackTagIds.includes(id))
            : tagFilter.some((id) => trackTagIds.includes(id));
        }
        const trackTagObjects = tags
          .filter((t) => trackTagIds.includes(t.id))
          .map((t) => ({ id: t.id, name: t.name, color: t.color }));
        return HttpResponse.json({
          items: include ? [{
            id: 't1', title: 't1', mix_name: null, artists: [],
            label: null, bpm: null, length_ms: null, publish_date: null,
            spotify_release_date: null, isrc: null, spotify_id: null,
            release_type: null, is_ai_suspected: false,
            added_at: '2026-05-11T00:00:00Z', source_triage_block_id: null,
            tags: trackTagObjects,
          }] : [],
          total: include ? 1 : 0, limit: 50, offset: 0,
        });
      }),
    );
  });

  it('create → assign → row pill appears', async () => {
    render(
      <W>
        <TracksTab categoryId="c1" styleId="s1" />
      </W>,
    );

    // 1. open manager and create a tag
    await userEvent.click(await screen.findByRole('button', { name: /manage tags/i }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: /new tag/i }));
    await userEvent.type(within(dialog).getByRole('textbox', { name: /name/i }), 'Vocal');
    await userEvent.click(within(dialog).getByRole('button', { name: /^create$/i }));
    await waitFor(() => expect(within(dialog).getByText('Vocal')).toBeInTheDocument());

    // 2. close manager, attach to track via popover
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const cellAddBtn = await screen.findByRole('button', { name: /add tag/i });
    await userEvent.click(cellAddBtn);
    await userEvent.click(await screen.findByRole('checkbox', { name: /vocal/i }));

    // 3. row pill appears (track row eventually carries the Vocal pill after refetch)
    await waitFor(() => {
      const pills = screen.getAllByText('Vocal');
      expect(pills.length).toBeGreaterThan(0);
    });
  });
});
