import { Group, Stack, Text, TextInput, Title } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { PageHeader } from '../../../components/PageHeader';
import { UserDailyTable, SessionsTable } from '../components/AnalyticsDashboard';

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

  return (
    <Stack>
      <PageHeader
        title={t('admin.analytics.title')}
        subtitle={t('admin.analytics.subtitle')}
        actions={
          <Group gap="xs" align="flex-end">
            <TextInput
              aria-label={t('admin.analytics.user_id')}
              label={t('admin.analytics.user_id')}
              placeholder="user-id"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
            />
            <input
              aria-label={t('admin.analytics.from')}
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
            <input
              aria-label={t('admin.analytics.to')}
              type="date"
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
