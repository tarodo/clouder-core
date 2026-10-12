import React from 'react';
import { beforeEach, describe, expect, it } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { FIRE_TAG_NAME, useFireTag } from '../useFireTag';

interface T {
  id: string;
  name: string;
  color: string | null;
}

const FIRE: T = { id: 'fire', name: FIRE_TAG_NAME, color: '#f97316' };
const VOCAL: T = { id: 'vocal', name: 'vocal', color: null };
const stamp = { created_at: 'x', updated_at: 'y' };

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

interface Calls {
  createdTags: unknown[];
  added: unknown[];
  removed: string[];
}

// Stateful fake of the tag routes: `vocabulary` is the user's tag list,
// `onTrack` the tag set of track t1.
function mockApi(
  vocabulary: T[],
  onTrack: T[],
  opts: { failAdd?: boolean; hold?: Promise<void> } = {},
) {
  const calls: Calls = { createdTags: [], added: [], removed: [] };
  const vocab = [...vocabulary];
  let own = [...onTrack];
  server.use(
    http.get('http://localhost/tags', () =>
      HttpResponse.json({
        items: vocab.map((t) => ({ ...t, ...stamp })),
        total: vocab.length,
        limit: 200,
        offset: 0,
      }),
    ),
    http.post('http://localhost/tags', async ({ request }) => {
      const body = (await request.json()) as { name: string; color: string | null };
      calls.createdTags.push(body);
      const tag: T = { id: 'fire-new', name: body.name, color: body.color };
      vocab.push(tag);
      return HttpResponse.json({ ...tag, ...stamp }, { status: 201 });
    }),
    http.get('http://localhost/tracks/t1/tags', () => HttpResponse.json({ tags: own })),
    http.post('http://localhost/tracks/t1/tags', async ({ request }) => {
      const body = (await request.json()) as { tag_id: string };
      calls.added.push(body);
      await opts.hold;
      if (opts.failAdd) return HttpResponse.json({ message: 'boom' }, { status: 500 });
      const tag = vocab.find((t) => t.id === body.tag_id)!;
      own = [...own, tag];
      return HttpResponse.json({ tags: own.map((t) => ({ ...t, ...stamp })) }, { status: 201 });
    }),
    http.delete('http://localhost/tracks/t1/tags/:tagId', ({ params }) => {
      calls.removed.push(String(params.tagId));
      own = own.filter((t) => t.id !== params.tagId);
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return calls;
}

describe('useFireTag', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('is active when the track already carries the fire tag', async () => {
    mockApi([FIRE, VOCAL], [VOCAL, FIRE]);
    const { result } = renderHook(() => useFireTag('t1'), { wrapper: wrap(makeClient()) });
    await waitFor(() => expect(result.current.active).toBe(true));
  });

  it('creates the fire tag on first use, then tags the track', async () => {
    const calls = mockApi([VOCAL], [VOCAL]);
    const { result } = renderHook(() => useFireTag('t1'), { wrapper: wrap(makeClient()) });
    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.active).toBe(false);

    act(() => result.current.toggle());

    await waitFor(() => expect(calls.added).toEqual([{ tag_id: 'fire-new' }]));
    expect(calls.createdTags).toEqual([{ name: FIRE_TAG_NAME, color: '#f97316' }]);
    await waitFor(() => expect(result.current.active).toBe(true));
  });

  it('reuses an existing fire tag instead of creating a second one', async () => {
    const calls = mockApi([FIRE, VOCAL], []);
    const { result } = renderHook(() => useFireTag('t1'), { wrapper: wrap(makeClient()) });
    await waitFor(() => expect(result.current.ready).toBe(true));

    act(() => result.current.toggle());

    await waitFor(() => expect(calls.added).toEqual([{ tag_id: 'fire' }]));
    expect(calls.createdTags).toEqual([]);
  });

  it('removes the fire tag when it is already on', async () => {
    const calls = mockApi([FIRE], [FIRE]);
    const { result } = renderHook(() => useFireTag('t1'), { wrapper: wrap(makeClient()) });
    await waitFor(() => expect(result.current.active).toBe(true));

    act(() => result.current.toggle());

    await waitFor(() => expect(result.current.active).toBe(false));
    await waitFor(() => expect(calls.removed).toEqual(['fire']));
  });

  it('rolls back the optimistic flag when tagging fails', async () => {
    let release!: () => void;
    const hold = new Promise<void>((r) => (release = r));
    const calls = mockApi([FIRE], [], { failAdd: true, hold });
    const { result } = renderHook(() => useFireTag('t1'), { wrapper: wrap(makeClient()) });
    await waitFor(() => expect(result.current.ready).toBe(true));

    act(() => result.current.toggle());
    await waitFor(() => expect(result.current.active).toBe(true)); // optimistic
    await waitFor(() => expect(calls.added).toHaveLength(1));

    release();
    await waitFor(() => expect(result.current.active).toBe(false));
  });

  it('ignores a second toggle while the first is in flight', async () => {
    const calls = mockApi([VOCAL], []);
    const { result } = renderHook(() => useFireTag('t1'), { wrapper: wrap(makeClient()) });
    await waitFor(() => expect(result.current.ready).toBe(true));

    act(() => {
      result.current.toggle();
      result.current.toggle();
    });

    await waitFor(() => expect(result.current.active).toBe(true));
    await waitFor(() => expect(calls.added).toHaveLength(1));
    expect(calls.createdTags).toHaveLength(1);
  });
});
