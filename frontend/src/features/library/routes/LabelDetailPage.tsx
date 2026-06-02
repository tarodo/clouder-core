import { Container, Grid, Card, Title, Text, Stack, Divider } from '@mantine/core';
import { useParams, Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { useLabelDetail } from '../hooks/useLabelDetail';
import { LabelDetailHeader } from '../components/LabelDetailHeader';
import { LabelChannelLinks } from '../components/LabelChannelLinks';
import { LabelOverviewTab } from '../components/LabelOverviewTab';
import { LabelStylesTab } from '../components/LabelStylesTab';
import { FullScreenLoader } from '../../../components/FullScreenLoader';

export function LabelDetailPage() {
  const { t } = useTranslation();
  const { labelId } = useParams<{ labelId: string }>();
  const query = useLabelDetail(labelId ?? null);
  if (!labelId) return <Navigate to="/library" replace />;

  if (query.isLoading) return <FullScreenLoader />;
  if (query.isError) {
    const is404 = query.error instanceof ApiError && query.error.status === 404;
    if (is404) {
      return (
        <Container py="md">
          <Stack gap="sm">
            <Title order={3}>{t('library.detail.no_info_title')}</Title>
            <Text c="dimmed">{t('library.detail.no_info_body')}</Text>
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
            <LabelDetailHeader info={info} labelId={labelId} />
            <Divider />
            <LabelOverviewTab info={info} />
            <Divider />
            <LabelStylesTab info={info} />
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 3 }}>
          <Card withBorder padding="md">
            <Title order={5} mb="sm">
              {t('library.detail.tab_links')}
            </Title>
            <LabelChannelLinks info={info} />
          </Card>
        </Grid.Col>
      </Grid>
    </Container>
  );
}
