import { Button } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconCopy } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { PlaylistTrack } from '../lib/playlistTypes';
import { buildPlaylistExport } from '../lib/playlistExport';

export interface CopyPlaylistButtonProps {
  playlistName: string;
  tracks: PlaylistTrack[];
}

export function CopyPlaylistButton({ playlistName, tracks }: CopyPlaylistButtonProps) {
  const { t } = useTranslation();

  async function handleCopy() {
    try {
      const json = JSON.stringify(buildPlaylistExport(playlistName, tracks), null, 2);
      await navigator.clipboard.writeText(json);
      notifications.show({
        color: 'green',
        message: t('playlists.copy.copied', { count: tracks.length }),
      });
    } catch {
      notifications.show({ color: 'red', message: t('playlists.copy.failed') });
    }
  }

  return (
    <Button
      leftSection={<IconCopy size={16} />}
      variant="outline"
      disabled={tracks.length === 0}
      onClick={() => void handleCopy()}
    >
      {t('playlists.copy.cta')}
    </Button>
  );
}
