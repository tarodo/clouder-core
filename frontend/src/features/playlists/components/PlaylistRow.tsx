import {
  ActionIcon,
  Anchor,
  Avatar,
  Group,
  Menu,
  Table,
  Text,
} from '@mantine/core';
import {
  IconBrandSpotify,
  IconDotsVertical,
  IconLock,
  IconLockOpen,
  IconPhoto,
} from '@tabler/icons-react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { notifications } from '@mantine/notifications';
import type { Playlist } from '../lib/playlistTypes';
import { DriftBadge } from './DriftBadge';
import { StatusBadge } from './StatusBadge';
import { useTogglePlaylistStatus } from '../hooks/useTogglePlaylistStatus';

export interface PlaylistRowProps {
  playlist: Playlist;
  onRename: (p: Playlist) => void;
  onEditDescription: (p: Playlist) => void;
  onDelete: (p: Playlist) => void;
}

export function PlaylistRow({
  playlist,
  onRename,
  onEditDescription,
  onDelete,
}: PlaylistRowProps) {
  const { t } = useTranslation();
  const toggleStatus = useTogglePlaylistStatus();
  const nextStatus = playlist.status === 'active' ? 'completed' : 'active';

  async function handleToggleStatus() {
    try {
      await toggleStatus.mutateAsync({ playlistId: playlist.id, status: nextStatus });
      notifications.show({
        message: t(
          nextStatus === 'completed'
            ? 'playlists.status.toast_completed'
            : 'playlists.status.toast_active',
        ),
        color: 'green',
      });
    } catch {
      notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
    }
  }

  return (
    <Table.Tr>
      <Table.Td>
        <Avatar
          src={playlist.cover_url}
          alt=""
          size={40}
          radius="sm"
          color="gray"
        >
          <IconPhoto size={16} />
        </Avatar>
      </Table.Td>
      <Table.Td>
        <Anchor
          component={Link}
          to={`/playlists/${playlist.id}`}
          c="var(--color-fg)"
          td="none"
          fw={500}
        >
          {playlist.name}
        </Anchor>
      </Table.Td>
      <Table.Td>{playlist.track_count}</Table.Td>
      <Table.Td>
        {playlist.is_public ? <IconLockOpen size={16} /> : <IconLock size={16} />}
      </Table.Td>
      <Table.Td>
        <StatusBadge status={playlist.status} />
      </Table.Td>
      <Table.Td>
        <Group gap="xs" wrap="nowrap">
          {playlist.spotify_playlist_id ? <IconBrandSpotify size={16} /> : null}
          {playlist.needs_republish ? <DriftBadge /> : null}
        </Group>
      </Table.Td>
      <Table.Td>
        <Text size="sm" c="dimmed">
          {playlist.updated_at.slice(0, 10)}
        </Text>
      </Table.Td>
      <Table.Td>
        <Menu withinPortal={false} transitionProps={{ duration: 0 }}>
          <Menu.Target>
            <ActionIcon variant="subtle" aria-label="Row actions">
              <IconDotsVertical size={18} />
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={() => onRename(playlist)}>
              {t('playlists.form.rename_title')}
            </Menu.Item>
            <Menu.Item onClick={() => onEditDescription(playlist)}>
              {t('playlists.form.edit_description_title')}
            </Menu.Item>
            <Menu.Item onClick={() => void handleToggleStatus()}>
              {nextStatus === 'completed'
                ? t('playlists.status.mark_completed')
                : t('playlists.status.mark_active')}
            </Menu.Item>
            <Menu.Item color="red" onClick={() => onDelete(playlist)}>
              {t('playlists.detail.delete_cta')}
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Table.Td>
    </Table.Tr>
  );
}
