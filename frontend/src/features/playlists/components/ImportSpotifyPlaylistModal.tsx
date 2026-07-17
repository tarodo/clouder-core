import { useMemo, useState } from 'react';
import { Alert, Button, Group, Modal, Stack, TextInput } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { parseSpotifyPlaylistRef } from '../lib/spotifyPlaylistRefParse';
import { InvalidSpotifyRefError } from '../lib/spotifyRefParse';
import { useImportSpotifyPlaylist } from '../hooks/useImportSpotifyPlaylist';
import { ApiError } from '../../../api/error';

export interface ImportSpotifyPlaylistModalProps {
  opened: boolean;
  onClose: () => void;
}

export function ImportSpotifyPlaylistModal({ opened, onClose }: ImportSpotifyPlaylistModalProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const importMut = useImportSpotifyPlaylist();
  const [url, setUrl] = useState('');
  const [name, setName] = useState('');
  const [serverError, setServerError] = useState<string | null>(null);

  const urlValid = useMemo(() => {
    try {
      parseSpotifyPlaylistRef(url);
      return true;
    } catch (e) {
      if (e instanceof InvalidSpotifyRefError) return false;
      return false;
    }
  }, [url]);

  function handleClose() {
    setUrl('');
    setName('');
    setServerError(null);
    onClose();
  }

  async function handleSubmit() {
    setServerError(null);
    try {
      const r = await importMut.mutateAsync({
        spotifyRef: url.trim(),
        name: name.trim() || undefined,
      });
      notifications.show({
        color: 'green',
        message: t(r.truncated ? 'playlists.importPlaylist.success_truncated' : 'playlists.importPlaylist.success', {
          count: r.imported,
          name: r.name,
        }),
      });
      handleClose();
      navigate(`/playlists/${r.playlist_id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setServerError(t('playlists.importPlaylist.name_conflict'));
      } else if (err instanceof ApiError && err.status === 412) {
        setServerError(t('playlists.errors.spotify_not_authorized'));
      } else if (err instanceof ApiError && err.status === 502) {
        setServerError(t('playlists.errors.spotify_upstream_error'));
      } else {
        setServerError(t('playlists.toast.generic_error'));
      }
    }
  }

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      size="lg"
      title={t('playlists.importPlaylist.title')}
      transitionProps={{ duration: 0 }}
    >
      <Stack gap="md">
        {serverError ? (
          <Alert color="red" icon={<IconAlertTriangle size={16} />}>
            {serverError}
          </Alert>
        ) : null}
        <TextInput
          label={t('playlists.importPlaylist.url_label')}
          placeholder={t('playlists.importPlaylist.url_placeholder')}
          value={url}
          onChange={(e) => setUrl(e.currentTarget.value)}
          error={url.length > 0 && !urlValid ? t('playlists.importPlaylist.invalid_url') : undefined}
        />
        <TextInput
          label={t('playlists.importPlaylist.name_label')}
          value={name}
          maxLength={100}
          onChange={(e) => setName(e.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button
            onClick={() => void handleSubmit()}
            loading={importMut.isPending}
            disabled={!urlValid}
          >
            {t('playlists.importPlaylist.submit')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
