import { Badge } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { PlaylistStatus } from '../lib/playlistTypes';

export interface StatusBadgeProps {
  status: PlaylistStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const { t } = useTranslation();
  if (status === 'completed') {
    return (
      <Badge color="gray" size="sm" variant="light">
        {t('playlists.status.completed')}
      </Badge>
    );
  }
  return (
    <Badge color="green" size="sm" variant="light">
      {t('playlists.status.active')}
    </Badge>
  );
}
