import { Select, Stack } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { PageHeader } from '../../../components/PageHeader';
import {
  FunnelCard,
  ListeningCard,
  TimePerTrackCard,
} from '../../analytics/components/AnalyticsCards';
import { useUsers } from '../hooks/useUsers';

export function AdminAnalyticsPage() {
  const { t } = useTranslation();
  const [userId, setUserId] = useState('');
  const users = useUsers();
  const options = (users.data?.users ?? []).map((u) => ({ value: u.id, label: u.display_name ?? u.id }));

  return (
    <Stack gap="xl">
      <PageHeader
        title={t('admin.analytics.title')}
        subtitle={t('admin.analytics.subtitle')}
        actions={
          <Select
            aria-label={t('admin.analytics.user')}
            placeholder={t('admin.analytics.me')}
            data={options}
            value={userId || null}
            onChange={(v) => setUserId(v ?? '')}
            searchable
            clearable
            disabled={users.isLoading}
          />
        }
      />
      <ListeningCard userId={userId} />
      <FunnelCard userId={userId} />
      <TimePerTrackCard userId={userId} />
    </Stack>
  );
}
