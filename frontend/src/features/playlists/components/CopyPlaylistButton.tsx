import { useState } from 'react';
import { Button } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconCopy } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { api } from '../../../api/client';
import type { PlaylistExport } from '../lib/playlistExport';

export interface CopyPlaylistButtonProps {
  playlistId: string;
  trackCount: number;
}

export function CopyPlaylistButton({ playlistId, trackCount }: CopyPlaylistButtonProps) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);

  async function handleCopy() {
    setLoading(true);
    try {
      // One round trip. The server assembles tracks, YouTube comments and the
      // merged enrichment blob for every artist and label; doing it here would
      // cost an /artists/{id} or /labels/{id} call per entity.
      const data = await api<PlaylistExport>(`/playlists/${playlistId}/export`);
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      notifications.show({
        color: 'green',
        message: t('playlists.copy.copied', { count: data.track_count }),
      });
    } catch {
      notifications.show({ color: 'red', message: t('playlists.copy.failed') });
    } finally {
      setLoading(false);
    }
  }

  return (
    <Button
      leftSection={<IconCopy size={16} />}
      variant="outline"
      disabled={trackCount === 0}
      loading={loading}
      onClick={() => void handleCopy()}
    >
      {t('playlists.copy.cta')}
    </Button>
  );
}
