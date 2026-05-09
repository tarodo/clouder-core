import { Stack, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { SpotifyNotFoundTable } from '../components/SpotifyNotFoundTable';

export function AdminSpotifyNotFoundPage() {
  const { t } = useTranslation();
  return (
    <Stack>
      <Title order={2}>{t('admin.spotify_not_found.title')}</Title>
      <SpotifyNotFoundTable />
    </Stack>
  );
}
