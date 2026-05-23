import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, act } from '@testing-library/react';
import { usePlaylistAddTrackTag, usePlaylistRemoveTrackTag } from '../usePlaylistTrackTag';
import { playlistTracksKey } from '../../lib/queryKeys';
import type { PaginatedPlaylistTracks } from '../../lib/playlistTypes';

vi.mock('../../../../api/client');

import { api } from '../../../../api/client';
const mockApi = vi.mocked(api);

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

const PLAYLIST_ID = 'pl-1';
const TRACK_ID = 'tr-1';

function seedCache(qc: QueryClient): PaginatedPlaylistTracks {
  const data: PaginatedPlaylistTracks = {
    items: [
      {
        track_id: TRACK_ID,
        position: 1,
        added_at: '2026-01-01T00:00:00Z',
        title: 'Test Track',
        spotify_id: null,
        isrc: null,
        length_ms: null,
        origin: 'beatport',
        mix_name: null,
        artists: [],
        label: null,
        bpm: null,
        spotify_release_date: null,
        is_ai_suspected: false,
        tags: [],
      },
    ],
    total: 1,
    limit: 50,
    offset: 0,
  };
  qc.setQueryData(playlistTracksKey(PLAYLIST_ID), data);
  return data;
}

describe('usePlaylistAddTrackTag', () => {
  beforeEach(() => {
    mockApi.mockResolvedValue(undefined as never);
  });

  it('optimistically adds the tag to the playlist tracks cache', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    seedCache(qc);

    const { result } = renderHook(() => usePlaylistAddTrackTag(PLAYLIST_ID), {
      wrapper: makeWrapper(qc),
    });

    const tag = { id: 'tg-1', name: 'house', color: '#ff0000' };

    await act(async () => {
      await result.current.mutateAsync({ trackId: TRACK_ID, tag });
    });

    const patched = qc.getQueryData<PaginatedPlaylistTracks>(playlistTracksKey(PLAYLIST_ID));
    const track = patched?.items.find((it) => it.track_id === TRACK_ID);
    expect(track?.tags).toContainEqual(tag);
  });

  it('calls POST /tracks/{id}/tags with tag_id', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    seedCache(qc);

    const { result } = renderHook(() => usePlaylistAddTrackTag(PLAYLIST_ID), {
      wrapper: makeWrapper(qc),
    });

    const tag = { id: 'tg-2', name: 'techno', color: null };

    await act(async () => {
      await result.current.mutateAsync({ trackId: TRACK_ID, tag });
    });

    expect(mockApi).toHaveBeenCalledWith(
      `/tracks/${TRACK_ID}/tags`,
      { method: 'POST', body: JSON.stringify({ tag_id: tag.id }) },
    );
  });

  it('does not duplicate a tag already in the cache', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const existing = { id: 'tg-3', name: 'existing', color: null };
    const data: PaginatedPlaylistTracks = {
      items: [{
        track_id: TRACK_ID,
        position: 1,
        added_at: '2026-01-01T00:00:00Z',
        title: 'T',
        spotify_id: null,
        isrc: null,
        length_ms: null,
        origin: 'beatport',
        mix_name: null,
        artists: [],
        label: null,
        bpm: null,
        spotify_release_date: null,
        is_ai_suspected: false,
        tags: [existing],
      }],
      total: 1,
      limit: 50,
      offset: 0,
    };
    qc.setQueryData(playlistTracksKey(PLAYLIST_ID), data);

    const { result } = renderHook(() => usePlaylistAddTrackTag(PLAYLIST_ID), {
      wrapper: makeWrapper(qc),
    });

    await act(async () => {
      await result.current.mutateAsync({ trackId: TRACK_ID, tag: existing });
    });

    const patched = qc.getQueryData<PaginatedPlaylistTracks>(playlistTracksKey(PLAYLIST_ID));
    const track = patched?.items.find((it) => it.track_id === TRACK_ID);
    expect(track?.tags.filter((t) => t.id === existing.id).length).toBe(1);
  });

  it('rolls back the cache on API error', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const original = seedCache(qc);
    mockApi.mockRejectedValueOnce(new Error('Network error'));

    const { result } = renderHook(() => usePlaylistAddTrackTag(PLAYLIST_ID), {
      wrapper: makeWrapper(qc),
    });

    const tag = { id: 'tg-fail', name: 'fail', color: null };

    await act(async () => {
      try {
        await result.current.mutateAsync({ trackId: TRACK_ID, tag });
      } catch {
        // expected
      }
    });

    const rolled = qc.getQueryData<PaginatedPlaylistTracks>(playlistTracksKey(PLAYLIST_ID));
    expect(rolled?.items[0]?.tags).toEqual(original.items[0]?.tags);
  });
});

describe('usePlaylistRemoveTrackTag', () => {
  beforeEach(() => {
    mockApi.mockResolvedValue(undefined as never);
  });

  it('optimistically removes the tag from the playlist tracks cache', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const tag = { id: 'tg-del', name: 'delete-me', color: null };
    const data: PaginatedPlaylistTracks = {
      items: [{
        track_id: TRACK_ID,
        position: 1,
        added_at: '2026-01-01T00:00:00Z',
        title: 'T',
        spotify_id: null,
        isrc: null,
        length_ms: null,
        origin: 'beatport',
        mix_name: null,
        artists: [],
        label: null,
        bpm: null,
        spotify_release_date: null,
        is_ai_suspected: false,
        tags: [tag],
      }],
      total: 1,
      limit: 50,
      offset: 0,
    };
    qc.setQueryData(playlistTracksKey(PLAYLIST_ID), data);

    const { result } = renderHook(() => usePlaylistRemoveTrackTag(PLAYLIST_ID), {
      wrapper: makeWrapper(qc),
    });

    await act(async () => {
      await result.current.mutateAsync({ trackId: TRACK_ID, tagId: tag.id });
    });

    const patched = qc.getQueryData<PaginatedPlaylistTracks>(playlistTracksKey(PLAYLIST_ID));
    const track = patched?.items.find((it) => it.track_id === TRACK_ID);
    expect(track?.tags).not.toContainEqual(tag);
    expect(track?.tags.length).toBe(0);
  });

  it('calls DELETE /tracks/{id}/tags/{tagId}', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const tag = { id: 'tg-del2', name: 'bye', color: null };
    const data: PaginatedPlaylistTracks = {
      items: [{
        track_id: TRACK_ID,
        position: 1,
        added_at: '2026-01-01T00:00:00Z',
        title: 'T',
        spotify_id: null,
        isrc: null,
        length_ms: null,
        origin: 'beatport',
        mix_name: null,
        artists: [],
        label: null,
        bpm: null,
        spotify_release_date: null,
        is_ai_suspected: false,
        tags: [tag],
      }],
      total: 1,
      limit: 50,
      offset: 0,
    };
    qc.setQueryData(playlistTracksKey(PLAYLIST_ID), data);

    const { result } = renderHook(() => usePlaylistRemoveTrackTag(PLAYLIST_ID), {
      wrapper: makeWrapper(qc),
    });

    await act(async () => {
      await result.current.mutateAsync({ trackId: TRACK_ID, tagId: tag.id });
    });

    expect(mockApi).toHaveBeenCalledWith(
      `/tracks/${TRACK_ID}/tags/${tag.id}`,
      { method: 'DELETE' },
    );
  });

  it('rolls back the cache on API error', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const tag = { id: 'tg-rollback', name: 'stay', color: null };
    const data: PaginatedPlaylistTracks = {
      items: [{
        track_id: TRACK_ID,
        position: 1,
        added_at: '2026-01-01T00:00:00Z',
        title: 'T',
        spotify_id: null,
        isrc: null,
        length_ms: null,
        origin: 'beatport',
        mix_name: null,
        artists: [],
        label: null,
        bpm: null,
        spotify_release_date: null,
        is_ai_suspected: false,
        tags: [tag],
      }],
      total: 1,
      limit: 50,
      offset: 0,
    };
    qc.setQueryData(playlistTracksKey(PLAYLIST_ID), data);
    mockApi.mockRejectedValueOnce(new Error('Network error'));

    const { result } = renderHook(() => usePlaylistRemoveTrackTag(PLAYLIST_ID), {
      wrapper: makeWrapper(qc),
    });

    await act(async () => {
      try {
        await result.current.mutateAsync({ trackId: TRACK_ID, tagId: tag.id });
      } catch {
        // expected
      }
    });

    const rolled = qc.getQueryData<PaginatedPlaylistTracks>(playlistTracksKey(PLAYLIST_ID));
    const track = rolled?.items.find((it) => it.track_id === TRACK_ID);
    expect(track?.tags).toContainEqual(tag);
  });
});
