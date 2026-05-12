import { Anchor, Loader, Menu, Text } from '@mantine/core';
import { Link } from 'react-router';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { usePlaylists } from '../../playlists/hooks/usePlaylists';
import { useAddTracksToPlaylist } from '../../playlists/hooks/useAddTracksToPlaylist';

export interface AddToPlaylistSubmenuProps {
  trackId: string;
}

export function AddToPlaylistSubmenu({ trackId }: AddToPlaylistSubmenuProps) {
  const { t } = useTranslation();
  // Always-enabled — Mantine renders Menu.Dropdown content lazily, so this
  // query only fires when the menu opens (parent Menu component gates render).
  const q = usePlaylists({ limit: 200 });
  const addMut = useAddTracksToPlaylist();

  async function handleAdd(playlistId: string, playlistName: string) {
    try {
      await addMut.mutateAsync({ playlistId, trackIds: [trackId] });
      notifications.show({
        message: t('playlists.toast.track_added', { name: playlistName }),
        color: 'green',
      });
    } catch {
      notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
    }
  }

  return (
    <>
      <Menu.Label>{t('categories.row_actions.add_to_playlist_label')}</Menu.Label>
      {q.isLoading ? (
        <Menu.Item disabled leftSection={<Loader size={12} />}>
          {t('categories.row_actions.loading')}
        </Menu.Item>
      ) : (q.data?.items.length ?? 0) === 0 ? (
        <>
          <Menu.Item disabled>{t('categories.row_actions.add_to_playlist_empty')}</Menu.Item>
          <Menu.Item>
            <Anchor component={Link} to="/playlists" td="none">
              <Text size="sm">{t('categories.row_actions.manage_playlists')}</Text>
            </Anchor>
          </Menu.Item>
        </>
      ) : (
        q.data!.items.map((p) => (
          <Menu.Item key={p.id} onClick={() => void handleAdd(p.id, p.name)}>
            {p.name}
          </Menu.Item>
        ))
      )}
    </>
  );
}
