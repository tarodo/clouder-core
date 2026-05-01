import { useCallback, useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import { categoriesByStyleKey, type PaginatedCategories } from './useCategoriesByStyle';

const DEBOUNCE_MS = 200;

export interface ReorderHandle {
  queueOrder: (categoryIds: string[]) => void;
  flushNow: () => Promise<void>;
}

export function useReorderCategories(styleId: string): ReorderHandle {
  const qc = useQueryClient();
  const { t } = useTranslation();
  const latestRef = useRef<string[] | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Subscribe to the categories query to keep it in cache (prevents GC while mounted).
  // enabled:false means we never fetch here — we just hold an observer reference so
  // the cached data set by useCategoriesByStyle isn't garbage-collected mid-DnD.
  useQuery<PaginatedCategories>({
    queryKey: categoriesByStyleKey(styleId),
    queryFn: () => Promise.reject(new Error('not used')),
    enabled: false,
    staleTime: Infinity,
  });

  const mutation = useMutation<unknown, Error, string[]>({
    mutationFn: (categoryIds) =>
      api(`/styles/${styleId}/categories/order`, {
        method: 'PUT',
        body: JSON.stringify({ category_ids: categoryIds }),
      }),
    onError: (err) => {
      const isMismatch =
        err instanceof ApiError && err.status === 422 && err.code === 'order_mismatch';
      void qc.invalidateQueries({ queryKey: categoriesByStyleKey(styleId) });
      try {
        notifications.show({
          message: isMismatch
            ? t('categories.toast.race_refreshed')
            : t('categories.toast.generic_error'),
          color: isMismatch ? 'yellow' : 'red',
        });
      } catch {
        // notifications may not be mounted in test environment
      }
    },
  });

  const flush = useCallback(async () => {
    const order = latestRef.current;
    latestRef.current = null;
    timerRef.current = null;
    if (!order) return;
    await mutation.mutateAsync(order).catch(() => {
      // onError handler above handles side effects; suppress unhandled rejection
    });
  }, [mutation]);

  const queueOrder = useCallback(
    (categoryIds: string[]) => {
      latestRef.current = categoryIds;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        void flush();
      }, DEBOUNCE_MS);
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
