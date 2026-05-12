import { Table } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { Playlist } from '../lib/playlistTypes';
import { PlaylistRow } from './PlaylistRow';

export interface PlaylistsTableProps {
  playlists: Playlist[];
  onRename: (p: Playlist) => void;
  onEditDescription: (p: Playlist) => void;
  onDelete: (p: Playlist) => void;
}

export function PlaylistsTable({
  playlists,
  onRename,
  onEditDescription,
  onDelete,
}: PlaylistsTableProps) {
  const { t } = useTranslation();
  return (
    <Table striped withTableBorder>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('playlists.table.col_cover')}</Table.Th>
          <Table.Th>{t('playlists.table.col_name')}</Table.Th>
          <Table.Th>{t('playlists.table.col_tracks')}</Table.Th>
          <Table.Th>{t('playlists.table.col_public')}</Table.Th>
          <Table.Th>{t('playlists.table.col_spotify')}</Table.Th>
          <Table.Th>{t('playlists.table.col_updated')}</Table.Th>
          <Table.Th>{t('playlists.table.col_actions')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {playlists.map((p) => (
          <PlaylistRow
            key={p.id}
            playlist={p}
            onRename={onRename}
            onEditDescription={onEditDescription}
            onDelete={onDelete}
          />
        ))}
      </Table.Tbody>
    </Table>
  );
}
