import { Container, Grid, Card, Title, Text, Stack, Divider } from '@mantine/core';
import { useParams, Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { useArtistDetail } from '../hooks/useArtistDetail';
import { ArtistDetailHeader } from '../components/ArtistDetailHeader';
import { ArtistChannelLinks } from '../components/ArtistChannelLinks';
import { ArtistOverviewTab } from '../components/ArtistOverviewTab';
import { ArtistStylesTab } from '../components/ArtistStylesTab';
import { FullScreenLoader } from '../../../components/FullScreenLoader';

export function ArtistDetailPage() {
  const { t } = useTranslation();
  const { styleId, artistId } = useParams<{ styleId: string; artistId: string }>();
  const query = useArtistDetail(artistId ?? null);
  if (!styleId || !artistId) return <Navigate to="/library" replace />;

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
            <ArtistDetailHeader info={info} styleId={styleId} artistId={artistId} />
            <Divider />
            <ArtistOverviewTab info={info} />
            <Divider />
            <ArtistStylesTab info={info} />
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 3 }}>
          <Card withBorder padding="md">
            <Title order={5} mb="sm">
              {t('library.detail.tab_links')}
            </Title>
            <ArtistChannelLinks info={info} />
          </Card>
        </Grid.Col>
      </Grid>
    </Container>
  );
}
