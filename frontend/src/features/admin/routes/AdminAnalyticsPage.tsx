import { Group, Stack } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { PageHeader } from '../../../components/PageHeader';
import { AnalyticsDashboard } from '../components/AnalyticsDashboard';
import { DASHBOARDS } from '../lib/dashboards';

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

export function AdminAnalyticsPage() {
  const { t } = useTranslation();
  const [from, setFrom] = useState(() => isoDaysAgo(30));
  const [to, setTo] = useState(() => isoDaysAgo(0));
  const range = { from, to };

  return (
    <Stack>
      <PageHeader
        title={t('admin.analytics.title')}
        subtitle={t('admin.analytics.subtitle')}
        actions={
          <Group gap="xs">
            <input aria-label={t('admin.analytics.from')} type="date" value={from}
              onChange={(e) => setFrom(e.target.value)} />
            <input aria-label={t('admin.analytics.to')} type="date" value={to}
              onChange={(e) => setTo(e.target.value)} />
          </Group>
        }
      />
      {DASHBOARDS.map((spec) => (
        <AnalyticsDashboard key={spec.name} spec={spec} range={range} />
      ))}
    </Stack>
  );
}
