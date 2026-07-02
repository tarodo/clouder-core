import { Group, Select, Stack, Text, TextInput, Title } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { PageHeader } from '../../../components/PageHeader';
import { UserDailyTable, SessionsTable } from '../components/AnalyticsDashboard';
import { useUsers } from '../hooks/useAnalytics';

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

export function AdminAnalyticsPage() {
  const { t } = useTranslation();
  const [userId, setUserId] = useState('');
  const [from, setFrom] = useState(() => isoDaysAgo(30));
  const [to, setTo] = useState(() => isoDaysAgo(0));
  const range = { from, to };

  const { data: usersData, isLoading: usersLoading } = useUsers();
  const userOptions = (usersData?.users ?? []).map((u) => ({
    value: u.id,
    label: u.display_name ?? u.id,
  }));

  return (
    <Stack>
      <PageHeader
        title={t('admin.analytics.title')}
        subtitle={t('admin.analytics.subtitle')}
        actions={
          <Group gap="sm" align="flex-end">
            <Select
              label={t('admin.analytics.user_id')}
              aria-label={t('admin.analytics.user_id')}
              placeholder={t('admin.analytics.pick_user')}
              data={userOptions}
              value={userId || null}
              onChange={(v) => setUserId(v ?? '')}
              searchable
              clearable
              disabled={usersLoading}
            />
            <TextInput
              type="date"
              label={t('admin.analytics.from')}
              aria-label={t('admin.analytics.from')}
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
            <TextInput
              type="date"
              label={t('admin.analytics.to')}
              aria-label={t('admin.analytics.to')}
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
          </Group>
        }
      />

      {userId.trim().length === 0 ? (
        <Text c="dimmed" ta="center" py="xl">
          {t('admin.analytics.pick_user')}
        </Text>
      ) : (
        <Stack gap="xl">
          <Stack gap="xs">
            <Title order={4}>{t('admin.analytics.col.date')} × Activity</Title>
            <UserDailyTable userId={userId} range={range} />
          </Stack>
          <Stack gap="xs">
            <Title order={4}>Sessions</Title>
            <SessionsTable userId={userId} range={range} />
          </Stack>
        </Stack>
      )}
    </Stack>
  );
}
