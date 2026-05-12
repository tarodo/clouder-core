import { useMemo, useState } from 'react';
import { Anchor, Breadcrumbs, Button, Group, Stack, TextInput } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconBrandSpotify, IconPlus, IconSearch } from '@tabler/icons-react';
import { Link, Navigate, useNavigate, useParams } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { EmptyState } from '../../../components/EmptyState';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { usePlaylistDetail } from '../hooks/usePlaylistDetail';
import { usePlaylistTracks } from '../hooks/usePlaylistTracks';
import { usePatchPlaylist } from '../hooks/usePatchPlaylist';
import { useDeletePlaylist } from '../hooks/useDeletePlaylist';
import { useRemoveTrackFromPlaylist } from '../hooks/useRemoveTrackFromPlaylist';
import { useReorderPlaylistTracks } from '../hooks/useReorderPlaylistTracks';
import { PlaylistMetaPanel } from '../components/PlaylistMetaPanel';
import { PlaylistTracksList } from '../components/PlaylistTracksList';
import { PublishButton } from '../components/PublishButton';
import { AddTracksModal } from '../components/AddTracksModal';
import { ImportSpotifyModal } from '../components/ImportSpotifyModal';
import { playlistTracksKey } from '../lib/queryKeys';
import type { PaginatedPlaylistTracks, PlaylistTrack } from '../lib/playlistTypes';

export function PlaylistDetailPage() {
  const { id } = useParams<{ id: string }>();
  if (!id) return <Navigate to="/playlists" replace />;
  return <PlaylistDetailPageInner id={id} />;
}

function PlaylistDetailPageInner({ id }: { id: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const detailQ = usePlaylistDetail(id);
  const tracksQ = usePlaylistTracks(id);
  const patchMut = usePatchPlaylist(id);
  const deleteMut = useDeletePlaylist();
  const removeTrackMut = useRemoveTrackFromPlaylist();
  const reorder = useReorderPlaylistTracks(id);

  const [search, setSearch] = useState('');
  const [addOpen, setAddOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  const tracks = useMemo(() => tracksQ.data?.items ?? [], [tracksQ.data?.items]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return tracks;
    return tracks.filter((tr) => tr.title.toLowerCase().includes(q));
  }, [tracks, search]);

  async function handlePatch(input: {
    name?: string;
    description?: string | null;
    is_public?: boolean;
  }) {
    try {
      await patchMut.mutateAsync(input);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        notifications.show({ message: t('playlists.errors.name_conflict'), color: 'red' });
      } else {
        notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
      }
      throw err;
    }
  }

  function handleReorder(orderedIds: string[]) {
    const cur = qc.getQueryData<PaginatedPlaylistTracks>(playlistTracksKey(id));
    if (!cur) return;
    const byId = new Map(cur.items.map((tr) => [tr.track_id, tr]));
    qc.setQueryData<PaginatedPlaylistTracks>(playlistTracksKey(id), {
      ...cur,
      items: orderedIds.map((tid, idx) => ({
        ...(byId.get(tid) as PlaylistTrack),
        position: idx,
      })),
    });
    reorder.queueOrder(orderedIds);
  }

  async function handleRemoveTrack(track: PlaylistTrack) {
    try {
      await removeTrackMut.mutateAsync({ playlistId: id, trackId: track.track_id });
      notifications.show({ message: t('playlists.toast.track_removed'), color: 'green' });
    } catch {
      notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
    }
  }

  function openDelete() {
    if (!detailQ.data) return;
    const p = detailQ.data;
    modals.openConfirmModal({
      title: t('playlists.detail.delete_cta'),
      children: p.name,
      labels: { confirm: t('playlists.detail.delete_cta'), cancel: t('playlists.form.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await deleteMut.mutateAsync(p.id);
          notifications.show({ message: t('playlists.toast.deleted'), color: 'green' });
          navigate('/playlists');
        } catch {
          notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
        }
      },
    });
  }

  if (detailQ.isLoading) return <FullScreenLoader />;
  if (detailQ.isError) {
    if (detailQ.error instanceof ApiError && detailQ.error.status === 404) {
      return (
        <EmptyState
          title={t('errors.not_found')}
          body={
            <Anchor component={Link} to="/playlists">
              {t('playlists.detail.back_to_list')}
            </Anchor>
          }
        />
      );
    }
    return <EmptyState title={t('errors.unknown')} body={t('errors.server_error')} />;
  }
  if (!detailQ.data) return null;
  const playlist = detailQ.data;

  return (
    <Stack gap="lg">
      <Breadcrumbs>
        <Anchor component={Link} to="/playlists">
          {t('playlists.page_title')}
        </Anchor>
        <span>{playlist.name}</span>
      </Breadcrumbs>

      <PlaylistMetaPanel
        playlist={playlist}
        onPatch={handlePatch}
        publishSlot={
          <Group gap="sm" align="center">
            <PublishButton playlist={playlist} />
            <Button color="red" variant="subtle" onClick={openDelete}>
              {t('playlists.detail.delete_cta')}
            </Button>
          </Group>
        }
      />

      <Group gap="sm" wrap="wrap">
        <Button leftSection={<IconPlus size={16} />} onClick={() => setAddOpen(true)}>
          {t('playlists.detail.add_tracks_cta')}
        </Button>
        <Button
          leftSection={<IconBrandSpotify size={16} />}
          variant="default"
          onClick={() => setImportOpen(true)}
        >
          {t('playlists.detail.import_spotify_cta')}
        </Button>
        <TextInput
          placeholder={t('playlists.detail.tracks_search_placeholder')}
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
        />
      </Group>

      {tracks.length === 0 ? (
        <EmptyState
          title={t('playlists.detail.empty_tracks_title')}
          body={t('playlists.detail.empty_tracks_body')}
        />
      ) : (
        <PlaylistTracksList
          tracks={filtered}
          onReorder={search.trim() === '' ? handleReorder : () => {}}
          onRemove={handleRemoveTrack}
          reorderDisabled={search.trim() !== ''}
        />
      )}

      <AddTracksModal
        opened={addOpen}
        onClose={() => setAddOpen(false)}
        playlistId={id}
        onAdded={() => {
          /* invalidations happen inside the hook */
        }}
      />
      <ImportSpotifyModal
        opened={importOpen}
        onClose={() => setImportOpen(false)}
        playlistId={id}
      />
    </Stack>
  );
}
