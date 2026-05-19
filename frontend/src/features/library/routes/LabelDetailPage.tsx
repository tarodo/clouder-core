import { Container, Grid, Tabs, Card, Title, Text, Button, Stack } from '@mantine/core';
import { useParams, Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { useLabelDetail } from '../hooks/useLabelDetail';
import { LabelDetailHeader } from '../components/LabelDetailHeader';
import { LabelChannelLinks } from '../components/LabelChannelLinks';
import { LabelOverviewTab } from '../components/LabelOverviewTab';
import { LabelStylesTab } from '../components/LabelStylesTab';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { getAuthSnapshot } from '../../../auth/AuthProvider';

export function LabelDetailPage() {
  const { t } = useTranslation();
  const { styleId, labelId } = useParams<{ styleId: string; labelId: string }>();
  const query = useLabelDetail(labelId ?? null);
  const auth = getAuthSnapshot();
  const isAdmin = auth.status === 'authenticated' && auth.user.is_admin;
  if (!styleId || !labelId) return <Navigate to="/library" replace />;

  if (query.isLoading) return <FullScreenLoader />;
  if (query.isError) {
    const is404 = query.error instanceof ApiError && query.error.status === 404;
    if (is404) {
      return (
        <Container py="md">
          <Stack gap="sm">
            <Title order={3}>{t('library.detail.no_info_title')}</Title>
            <Text c="dimmed">{t('library.detail.no_info_body')}</Text>
            {isAdmin && (
              <Button component="a" href={`/admin/labels/enrich?label_id=${labelId}`}>
                {t('library.detail.admin_enqueue_cta')}
              </Button>
            )}
          </Stack>
        </Container>
      );
    }
    throw query.error;
  }
  if (!query.data) return null;
  const info = query.data;

  return (
    <Container size="lg" py="md">
      <Grid>
        <Grid.Col span={{ base: 12, lg: 9 }}>
          <Stack gap="md">
            <LabelDetailHeader info={info} styleId={styleId} />
            <Tabs defaultValue="overview">
              <Tabs.List>
                <Tabs.Tab value="overview">{t('library.detail.tab_overview')}</Tabs.Tab>
                <Tabs.Tab value="styles">{t('library.detail.tab_styles')}</Tabs.Tab>
              </Tabs.List>
              <Tabs.Panel value="overview" pt="md">
                <LabelOverviewTab info={info} />
              </Tabs.Panel>
              <Tabs.Panel value="styles" pt="md">
                <LabelStylesTab info={info} />
              </Tabs.Panel>
            </Tabs>
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 3 }}>
          <Card withBorder padding="md">
            <Title order={5} mb="sm">{t('library.detail.tab_links')}</Title>
            <LabelChannelLinks info={info} />
          </Card>
        </Grid.Col>
      </Grid>
    </Container>
  );
}
