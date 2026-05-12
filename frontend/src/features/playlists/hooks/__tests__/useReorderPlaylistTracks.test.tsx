import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { I18nextProvider } from 'react-i18next';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import i18n from '../../../../i18n';
import { useReorderPlaylistTracks } from '../useReorderPlaylistTracks';

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <I18nextProvider i18n={i18n}>
        <MantineProvider>
          <Notifications />
          <QueryClientProvider client={qc}>{children}</QueryClientProvider>
        </MantineProvider>
      </I18nextProvider>
    );
  };
}

describe('useReorderPlaylistTracks', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it('debounces and posts the latest order', async () => {
    let postedBody: { track_ids: string[] } | null = null;
    server.use(
      http.post('http://localhost/playlists/p1/tracks/order', async ({ request }) => {
        postedBody = (await request.json()) as { track_ids: string[] };
        return HttpResponse.json({ correlation_id: 'cid' });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useReorderPlaylistTracks('p1'), {
      wrapper: makeWrapper(qc),
    });

    act(() => {
      result.current.queueOrder(['t1', 't2', 't3']);
      result.current.queueOrder(['t3', 't2', 't1']);
    });
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(postedBody).toEqual({ track_ids: ['t3', 't2', 't1'] });
  });

  it('invalidates tracks cache on 400 order_mismatch', async () => {
    server.use(
      http.post('http://localhost/playlists/p1/tracks/order', () =>
        HttpResponse.json(
          { error_code: 'order_mismatch', message: 'mismatch' },
          { status: 400 },
        ),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useReorderPlaylistTracks('p1'), {
      wrapper: makeWrapper(qc),
    });
    act(() => result.current.queueOrder(['t1', 't2']));
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(
      invalidateSpy.mock.calls.some(
        ([arg]) =>
          Array.isArray(arg?.queryKey) &&
          arg.queryKey[0] === 'playlists' &&
          arg.queryKey[1] === 'tracks',
      ),
    ).toBe(true);
  });
});
