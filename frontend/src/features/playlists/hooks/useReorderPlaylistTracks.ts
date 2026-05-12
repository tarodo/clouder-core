import { useCallback, useEffect, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import { playlistTracksKey } from '../lib/queryKeys';

const DEBOUNCE_MS = 200;

export interface ReorderHandle {
  queueOrder: (trackIds: string[]) => void;
  flushNow: () => Promise<void>;
}

export function useReorderPlaylistTracks(playlistId: string): ReorderHandle {
  const qc = useQueryClient();
  const { t } = useTranslation();
  const latestRef = useRef<string[] | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const mutation = useMutation<unknown, Error, string[]>({
    mutationFn: (trackIds) =>
      api(`/playlists/${playlistId}/tracks/order`, {
        method: 'POST',
        body: JSON.stringify({ track_ids: trackIds }),
      }),
    onError: (err) => {
      const isMismatch =
        err instanceof ApiError && err.status === 400 && err.code === 'order_mismatch';
      void qc.invalidateQueries({ queryKey: playlistTracksKey(playlistId) });
      try {
        notifications.show({
          message: isMismatch
            ? t('playlists.toast.reorder_race')
            : t('playlists.toast.generic_error'),
          color: isMismatch ? 'yellow' : 'red',
        });
      } catch {
        // notifications may be unmounted in test environments
      }
    },
  });

  const flush = useCallback(async () => {
    const order = latestRef.current;
    latestRef.current = null;
    timerRef.current = null;
    if (!order) return;
    await mutation.mutateAsync(order).catch(() => {
      // onError handler manages user-facing side effects
    });
  }, [mutation]);

  const queueOrder = useCallback(
    (trackIds: string[]) => {
      latestRef.current = trackIds;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => void flush(), DEBOUNCE_MS);
    },
    [flush],
  );

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return { queueOrder, flushNow: flush };
}
