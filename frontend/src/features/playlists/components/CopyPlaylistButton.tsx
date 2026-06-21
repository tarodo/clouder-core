import { useState } from 'react';
import { Button } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconCopy } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { api } from '../../../api/client';
import type { PlaylistTrack, PlaylistCommentsResponse } from '../lib/playlistTypes';
import { buildPlaylistExport } from '../lib/playlistExport';

export interface CopyPlaylistButtonProps {
  playlistName: string;
  tracks: PlaylistTrack[];
  playlistId: string;
}

export function CopyPlaylistButton({ playlistName, tracks, playlistId }: CopyPlaylistButtonProps) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);

  async function handleCopy() {
    setLoading(true);
    try {
      const resp = await api<PlaylistCommentsResponse>(
        `/playlists/${playlistId}/comments?platform=youtube`,
      );
      const commentsByTrack = Object.fromEntries(
        resp.tracks.map((t) => [t.track_id, t.comments]),
      );
      const json = JSON.stringify(buildPlaylistExport(playlistName, tracks, commentsByTrack), null, 2);
      await navigator.clipboard.writeText(json);
      notifications.show({
        color: 'green',
        message: t('playlists.copy.copied', { count: tracks.length }),
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
      disabled={tracks.length === 0}
      loading={loading}
      onClick={() => void handleCopy()}
    >
      {t('playlists.copy.cta')}
    </Button>
  );
}
