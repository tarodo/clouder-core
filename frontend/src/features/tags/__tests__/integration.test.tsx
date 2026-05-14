import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('../../playback/usePlayback', () => ({
  usePlayback: () => ({
    controls: {
      prewarm: vi.fn(() => Promise.resolve()),
      play: vi.fn(() => Promise.resolve()),
      bindQueue: vi.fn(),
      clearQueue: vi.fn(),
    },
    queue: { source: null, tracks: [], cursor: 0, status: 'idle' },
    track: { current: null, positionMs: 0, durationMs: 0 },
    sdk: { ready: false, error: null },
    devices: {} as never,
  }),
}));
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
import { useState } from 'react';
import { useDebouncedValue } from '@mantine/hooks';
import { useSearchParams } from 'react-router';
import {
  useCategoryTracks,
  type CategoryTrackSort,
  type SortOrder,
} from '../../categories/hooks/useCategoryTracks';
import { readTagsUrlState } from '../index';
import { readFresh } from '../../categories/lib/freshUrlState';

function TracksTabHarness({ categoryId, styleId }: { categoryId: string; styleId: string }) {
  const [rawSearch, setRawSearch] = useState('');
  const [debounced] = useDebouncedValue(rawSearch.trim().toLowerCase(), 300);
  const [sortKey, setSortKey] = useState<CategoryTrackSort>('added_at');
  const [sortDir, setSortDir] = useState<SortOrder>('desc');
  const [searchParams] = useSearchParams();
  const tagFilter = readTagsUrlState(searchParams);
  const fresh = readFresh(searchParams);
  const q = useCategoryTracks(
    categoryId, debounced, sortKey, sortDir,
    tagFilter.selectedIds, tagFilter.match, fresh,
  );
  return (
    <TracksTab
      categoryId={categoryId}
      styleId={styleId}
      items={q.data?.pages.flatMap((p) => p.items) ?? []}
      total={q.data?.pages[0]?.total ?? 0}
      isLoading={q.isLoading}
      hasNextPage={!!q.hasNextPage}
      isFetchingNextPage={q.isFetchingNextPage}
      fetchNextPage={() => void q.fetchNextPage()}
      rawSearch={rawSearch}
      setRawSearch={setRawSearch}
      debounced={debounced}
      sortKey={sortKey}
      sortDir={sortDir}
      setSortKey={setSortKey}
      setSortDir={setSortDir}
      onPlay={() => {}}
    />
  );
}

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
    type Tag = { id: string; name: string; color: string | null; created_at: string; updated_at: string };
    type TrackTag = { track_id: string; tag_id: string };
    let tags: Tag[] = [];
    let trackTags: TrackTag[] = [];

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
        const trackId = String(params.trackId);
        if (!trackTags.some((t) => t.track_id === trackId && t.tag_id === body.tag_id)) {
          trackTags.push({ track_id: trackId, tag_id: body.tag_id });
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
        <TracksTabHarness categoryId="c1" styleId="s1" />
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
