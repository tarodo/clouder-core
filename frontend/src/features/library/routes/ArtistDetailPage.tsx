import { Grid, Card, Title, Stack, Divider } from '@mantine/core';
import { useParams, Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { useArtistDetail } from '../hooks/useArtistDetail';
import { ArtistDetailHeader } from '../components/ArtistDetailHeader';
import { ArtistChannelLinks } from '../components/ArtistChannelLinks';
import { ArtistOverviewTab } from '../components/ArtistOverviewTab';
import { ArtistStylesTab } from '../components/ArtistStylesTab';
import { EntityTracksSection } from '../components/EntityTracksSection';
import { PageSkeleton } from '../../../components/PageSkeleton';
import { EmptyState } from '../../../components/EmptyState';

export function ArtistDetailPage() {
  const { t } = useTranslation();
  const { artistId } = useParams<{ artistId: string }>();
  const query = useArtistDetail(artistId ?? null);
  if (!artistId) return <Navigate to="/library" replace />;

  if (query.isLoading) return <PageSkeleton breadcrumbs rows={6} rowHeight={64} />;
  if (query.isError) {
    const is404 = query.error instanceof ApiError && query.error.status === 404;
    if (is404) {
      return (
        <EmptyState
          variant="page"
          title={t('library.detail.no_info_title')}
          body={t('library.detail.no_info_body')}
        />
      );
    }
    throw query.error;
  }
  if (!query.data) return null;
  const info = query.data;

  // Full width like the category page: the player and the track list sit side by side.
  return (
    <Stack gap="lg">
      <ArtistDetailHeader info={info} artistId={artistId} />
      <EntityTracksSection kind="artist" entityId={artistId} />
      <Divider />
      <Grid>
        <Grid.Col span={{ base: 12, lg: 9 }}>
          <Stack gap="md" maw={900}>
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
    </Stack>
  );
}
