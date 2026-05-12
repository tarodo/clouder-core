import { Badge } from '@mantine/core';
import { IconBrandSpotify } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { PlaylistTrackOrigin } from '../lib/playlistTypes';

export function OriginBadge({ origin }: { origin: PlaylistTrackOrigin }) {
  const { t } = useTranslation();
  if (origin !== 'spotify_user_import') return null;
  return (
    <Badge color="green" leftSection={<IconBrandSpotify size={12} />} size="sm" variant="light">
      {t('playlists.origin.spotify')}
    </Badge>
  );
}
