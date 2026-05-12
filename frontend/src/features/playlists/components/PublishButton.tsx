import { useState } from 'react';
import { Anchor, Button, Group } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconBrandSpotify } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import type { Playlist, PublishResult } from '../lib/playlistTypes';
import { usePublishPlaylist } from '../hooks/usePublishPlaylist';
import { PublishConfirmModal } from './PublishConfirmModal';
import { PublishResultModal } from './PublishResultModal';
import { DriftBadge } from './DriftBadge';

export interface PublishButtonProps {
  playlist: Playlist;
}

export function PublishButton({ playlist }: PublishButtonProps) {
  const { t } = useTranslation();
  const publishMut = usePublishPlaylist();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [resultModal, setResultModal] = useState<PublishResult | null>(null);

  const alreadyPublished = !!playlist.spotify_playlist_id;

  function handleClick() {
    if (alreadyPublished) {
      setConfirmOpen(true);
    } else {
      void doPublish(false);
    }
  }

  async function doPublish(confirmOverwrite: boolean) {
    try {
      const r = await publishMut.mutateAsync({
        playlistId: playlist.id,
        confirmOverwrite,
      });
      setConfirmOpen(false);
      notifications.show({
        color: 'green',
        message: (
          <Group gap="sm">
            <span>
              {alreadyPublished
                ? t('playlists.toast.published_again')
                : t('playlists.toast.published_first')}
            </span>
            <Anchor href={r.spotify_url} target="_blank" rel="noopener noreferrer">
              {t('playlists.publish.open_in_spotify')}
            </Anchor>
          </Group>
        ),
      });
      if (r.cover_failed) {
        notifications.show({ message: t('playlists.publish.cover_failed'), color: 'yellow' });
      }
      if (r.skipped_tracks.length > 0) {
        setResultModal(r);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 400 && err.code === 'confirm_overwrite_required') {
        notifications.show({
          message: t('playlists.errors.confirm_overwrite_required'),
          color: 'yellow',
        });
        setConfirmOpen(true);
      } else if (err instanceof ApiError && err.status === 412) {
        notifications.show({
          message: t('playlists.errors.spotify_not_authorized'),
          color: 'red',
        });
      } else if (err instanceof ApiError && err.status === 502) {
        notifications.show({
          message: t('playlists.errors.spotify_upstream_error'),
          color: 'red',
        });
      } else {
        notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
      }
    }
  }

  return (
    <>
      <Group gap="sm" align="center">
        <Button
          leftSection={<IconBrandSpotify size={16} />}
          color="green"
          loading={publishMut.isPending}
          onClick={handleClick}
        >
          {alreadyPublished ? t('playlists.publish.again') : t('playlists.publish.first')}
        </Button>
        {playlist.needs_republish ? <DriftBadge /> : null}
      </Group>
      <PublishConfirmModal
        opened={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => void doPublish(true)}
        playlistName={playlist.name}
        trackCount={playlist.track_count}
        loading={publishMut.isPending}
      />
      <PublishResultModal
        opened={resultModal !== null}
        onClose={() => setResultModal(null)}
        result={resultModal}
      />
    </>
  );
}
