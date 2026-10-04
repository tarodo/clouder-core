import { Stack } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { PageHeader } from '../../../components/PageHeader';
import { FunnelSection, ListeningSection } from '../components/AnalyticsDashboard';

export function AdminAnalyticsPage() {
  const { t } = useTranslation();
  return (
    <Stack gap="xl">
      <PageHeader title={t('admin.analytics.title')} subtitle={t('admin.analytics.subtitle')} />
      <ListeningSection />
      <FunnelSection />
    </Stack>
  );
}
