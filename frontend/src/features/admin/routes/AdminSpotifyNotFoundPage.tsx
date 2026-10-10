import { Stack } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { SpotifyNotFoundTable } from '../components/SpotifyNotFoundTable';
import { SpotifySearchStatus } from '../components/SpotifySearchStatus';
import { PageHeader } from '../../../components/PageHeader';

export function AdminSpotifyNotFoundPage() {
  const { t } = useTranslation();
  return (
    <Stack>
      <PageHeader title={t('admin.spotify_not_found.title')} subtitle={t('admin.spotify_not_found.subtitle')} />
      <SpotifySearchStatus />
      <SpotifyNotFoundTable />
    </Stack>
  );
}
