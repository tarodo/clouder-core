import { useCallback, useEffect, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import { allStylesKey } from './useAllStyles';

const DEBOUNCE_MS = 200;

export interface UpdateMyStylesHandle {
  queueSelection: (styleIds: string[]) => void;
  flushNow: () => Promise<void>;
}

export function useUpdateMyStyles(): UpdateMyStylesHandle {
  const qc = useQueryClient();
  const { t } = useTranslation();
  const latestRef = useRef<string[] | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const mutation = useMutation<unknown, Error, string[]>({
    mutationFn: (styleIds) =>
      api('/me/styles', {
        method: 'PUT',
        body: JSON.stringify({ style_ids: styleIds }),
      }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ['styles'] });
      void qc.invalidateQueries({ queryKey: allStylesKey });
    },
    onError: () => {
      try {
        notifications.show({
          message: t('profile.styles.toast.save_failed'),
          color: 'red',
        });
      } catch {
        // notifications may not be mounted in the test environment
      }
    },
  });

  const flushNow = useCallback(async () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    const pending = latestRef.current;
    latestRef.current = null;
    if (pending) await mutation.mutateAsync(pending).catch(() => undefined);
  }, [mutation]);

  const queueSelection = useCallback(
    (styleIds: string[]) => {
      latestRef.current = styleIds;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        void flushNow();
      }, DEBOUNCE_MS);
    },
    [flushNow],
  );

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  return { queueSelection, flushNow };
}
