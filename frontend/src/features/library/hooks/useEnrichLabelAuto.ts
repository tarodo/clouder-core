import { useMutation } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';

interface Accepted {
  run_id: string;
  queued_labels: number;
}

export function useEnrichLabelAuto() {
  const { t } = useTranslation();
  return useMutation<Accepted, Error, { labelId: string }>({
    mutationFn: ({ labelId }) =>
      api<Accepted>(`/admin/labels/${labelId}/enrich-auto`, { method: 'POST' }),
    onSuccess: () => {
      notifications.show({ message: t('library.detail.admin_search_queued') });
    },
    onError: (err) => {
      const msg =
        err instanceof ApiError && err.status === 409
          ? t('library.detail.admin_search_not_configured')
          : t('library.detail.admin_search_failed');
      notifications.show({ color: 'red', message: msg });
    },
  });
}
