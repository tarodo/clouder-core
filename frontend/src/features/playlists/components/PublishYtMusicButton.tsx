import { useState } from 'react';
import { Anchor, Button, Group } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconBrandYoutube } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import type { Playlist, YtmusicPublishResult } from '../lib/playlistTypes';
import { usePublishYtmusic } from '../hooks/usePublishYtmusic';
import { useTelemetry } from '../../../lib/telemetry/hooks';
import { useMe } from '../../../api/queries/useMe';
import { PublishConfirmModal } from './PublishConfirmModal';
import { PublishResultModal } from './PublishResultModal';
import { YtMusicConnectModal } from './YtMusicConnectModal';

export interface PublishYtMusicButtonProps {
  playlist: Playlist;
  trackIds: string[];
}

export function PublishYtMusicButton({ playlist, trackIds }: PublishYtMusicButtonProps) {
  const { t } = useTranslation();
  const me = useMe();
  const publishMut = usePublishYtmusic();
  const telemetry = useTelemetry();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);
  const [resultModal, setResultModal] = useState<YtmusicPublishResult | null>(null);

  const alreadyPublished = !!playlist.ytmusic_playlist_id;

  function handleClick() {
    if (me.data && !me.data.ytmusic_connected) {
      setConnectOpen(true);
      return;
    }
    if (alreadyPublished) {
      setConfirmOpen(true);
    } else {
      void doPublish(false);
    }
  }

  async function doPublish(confirmOverwrite: boolean) {
    try {
      const r = await publishMut.mutateAsync({ playlistId: playlist.id, confirmOverwrite });
      setConfirmOpen(false);
      telemetry.track('playlist_publish', {
        track_ids: trackIds,
        playlist_id: playlist.id,
        track_count: trackIds.length,
        confirm_overwrite: confirmOverwrite,
        skipped_count: r.skipped_tracks.length,
        target: 'ytmusic',
      });
      notifications.show({
        color: 'green',
        message: (
          <Group gap="sm">
            <span>
              {alreadyPublished
                ? t('playlists.toast.ytmusic_published_again')
                : t('playlists.toast.ytmusic_published_first')}
            </span>
            <Anchor href={r.ytmusic_url} target="_blank" rel="noopener noreferrer">
              {t('playlists.publish.open_in_ytmusic')}
            </Anchor>
          </Group>
        ),
      });
      if (r.cover_failed) {
        notifications.show({ message: t('playlists.publish.ytmusic_cover_failed'), color: 'yellow' });
      }
      if (r.skipped_tracks.length > 0) setResultModal(r);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.code === 'confirm_overwrite_required') {
        setConfirmOpen(true);
      } else if (err instanceof ApiError && err.status === 412) {
        setConnectOpen(true);
      } else if (err instanceof ApiError && err.status === 502) {
        notifications.show({ message: t('playlists.errors.ytmusic_api_error'), color: 'red' });
      } else if (err instanceof ApiError && err.status === 400) {
        notifications.show({ message: err.message, color: 'yellow' });
      } else {
        notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
      }
    }
  }

  return (
    <>
      <Button
        leftSection={<IconBrandYoutube size={16} />}
        color="red"
        variant="outline"
        loading={publishMut.isPending}
        onClick={handleClick}
      >
        {alreadyPublished ? t('playlists.publish.ytmusic_again') : t('playlists.publish.ytmusic')}
      </Button>
      <PublishConfirmModal
        opened={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => void doPublish(true)}
        playlistName={playlist.name}
        trackCount={playlist.track_count}
        loading={publishMut.isPending}
      />
      <YtMusicConnectModal
        opened={connectOpen}
        onClose={() => setConnectOpen(false)}
        onConnected={() => {
          setConnectOpen(false);
          void me.refetch();
          if (alreadyPublished) setConfirmOpen(true);
          else void doPublish(false);
        }}
      />
      <PublishResultModal
        opened={resultModal !== null}
        onClose={() => setResultModal(null)}
        skippedTracks={resultModal?.skipped_tracks ?? null}
        openUrl={resultModal?.ytmusic_url ?? ''}
        openLabelKey="playlists.publish.open_in_ytmusic"
      />
    </>
  );
}
