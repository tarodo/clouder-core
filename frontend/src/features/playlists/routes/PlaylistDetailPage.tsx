import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActionIcon, Anchor, Breadcrumbs, Button, Flex, Group, Stack, TextInput, Tooltip, useMantineTheme } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconBrandSpotify, IconBrandYoutube, IconPlus, IconSearch } from '@tabler/icons-react';
import {
  Link,
  Navigate,
  Outlet,
  useMatch,
  useNavigate,
  useParams,
} from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { EmptyState } from '../../../components/EmptyState';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { usePlayback } from '../../playback/usePlayback';
import type { PlaybackTrack } from '../../playback/lib/types';
import { usePlaylistDetail } from '../hooks/usePlaylistDetail';
import { usePlaylistTracks } from '../hooks/usePlaylistTracks';
import { usePatchPlaylist } from '../hooks/usePatchPlaylist';
import { useDeletePlaylist } from '../hooks/useDeletePlaylist';
import { useRemoveTrackFromPlaylist } from '../hooks/useRemoveTrackFromPlaylist';
import { useReorderPlaylistTracks } from '../hooks/useReorderPlaylistTracks';
import { usePlaylistPlayerQueue } from '../hooks/usePlaylistPlayerQueue';
import { PlaylistMetaPanel } from '../components/PlaylistMetaPanel';
import { PlaylistTracksList } from '../components/PlaylistTracksList';
import { PlaylistPlayerPanel } from '../components/PlaylistPlayerPanel';
import { PublishButton } from '../components/PublishButton';
import { PublishYtMusicButton } from '../components/PublishYtMusicButton';
import { DriftBadge } from '../components/DriftBadge';
import { AddTracksModal } from '../components/AddTracksModal';
import { ImportSpotifyModal } from '../components/ImportSpotifyModal';
import { playlistTracksKey } from '../lib/queryKeys';
import type { PaginatedPlaylistTracks, PlaylistTrack } from '../lib/playlistTypes';

function toPlaybackTrack(t: PlaylistTrack): PlaybackTrack {
  return {
    id: t.track_id,
    title: t.title,
    artists: t.artists.map((a) => a.name).join(', '),
    duration_ms: t.length_ms ?? 0,
    spotify_id: t.spotify_id,
    cover_url: null,
  };
}

export type PlaylistDetailOutletContext = {
  items: PlaylistTrack[];
};

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
  const playback = usePlayback();
  const theme = useMantineTheme();
  const isDesktop = useMediaQuery(`(min-width: ${theme.breakpoints.md})`);
  // Mobile uses a fullscreen player route nested under this one. When the
  // nested /player route is active, render <Outlet> instead of the layout —
  // parent stays mounted so queue state survives navigation.
  const onPlayerSubpath = useMatch({ path: '/playlists/:id/player', end: false });

  const [search, setSearch] = useState('');
  const [addOpen, setAddOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  // Pre-warm SDK on mount so first play happens inside the user-gesture window.
  useEffect(() => {
    void playback.controls.prewarm();
  }, [playback.controls]);

  const tracks = useMemo(() => tracksQ.data?.items ?? [], [tracksQ.data?.items]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return tracks;
    return tracks.filter((tr) => tr.title.toLowerCase().includes(q));
  }, [tracks, search]);

  const playerTracks = useMemo<PlaybackTrack[]>(() => tracks.map(toPlaybackTrack), [tracks]);
  usePlaylistPlayerQueue(id, playerTracks);

  const onPlay = useCallback(
    (track: PlaylistTrack) => {
      if (!track.spotify_id) return;
      void playback.controls.prewarm();
      const queueIdx = playback.queue.tracks.findIndex((q) => q.id === track.track_id);
      if (queueIdx >= 0) {
        void playback.controls.play(queueIdx);
      } else {
        void playback.controls.play(undefined, toPlaybackTrack(track));
      }
      if (!isDesktop) {
        navigate(`/playlists/${id}/player`);
      }
    },
    [playback.controls, playback.queue.tracks, isDesktop, navigate, id],
  );

  async function handlePatch(input: {
    name?: string;
    description?: string | null;
    is_public?: boolean;
    status?: 'active' | 'completed';
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

  // When the nested /player route is active (mobile only), render just the
  // outlet — the queue + state above already includes the user's visible list,
  // so the player has the right context. Items are forwarded via outlet context
  // so the child page can pass them to PlaylistPlayerPanel for rich metadata lookup.
  if (onPlayerSubpath) {
    return <Outlet context={{ items: tracks } satisfies PlaylistDetailOutletContext} />;
  }

  // Shared playlist-wide controls — live above the player + list split.
  const controls = (
    <Group gap="sm" wrap="wrap">
      <Button leftSection={<IconPlus size={16} />} variant="light" onClick={() => setAddOpen(true)}>
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
        style={{ width: 280 }}
      />
    </Group>
  );

  const tilesList = (
    <Stack gap="md">
      {controls}
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
          onPlayTrack={onPlay}
          currentTrackId={playback.track.current?.id ?? null}
          playlistId={id}
        />
      )}
    </Stack>
  );

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
        titleSlot={
          <Group gap="xs" align="center">
            {playlist.needs_republish ? <DriftBadge /> : null}
            <Button color="red" variant="subtle" size="xs" onClick={openDelete}>
              {t('playlists.detail.delete_cta')}
            </Button>
          </Group>
        }
        publishSlot={
          <Group gap="sm" align="center">
            <PublishButton playlist={playlist} />
            <PublishYtMusicButton playlist={playlist} />
            {playlist.spotify_playlist_id ? (
              <Tooltip label={t('playlists.detail.open_spotify')} withinPortal>
                <ActionIcon
                  component="a"
                  href={`https://open.spotify.com/playlist/${playlist.spotify_playlist_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  variant="subtle"
                  color="gray"
                  size="lg"
                  aria-label={t('playlists.detail.open_spotify')}
                >
                  <IconBrandSpotify size={22} />
                </ActionIcon>
              </Tooltip>
            ) : null}
            {playlist.ytmusic_playlist_id ? (
              <Tooltip label={t('playlists.detail.open_ytmusic')} withinPortal>
                <ActionIcon
                  component="a"
                  href={`https://music.youtube.com/playlist?list=${playlist.ytmusic_playlist_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  variant="subtle"
                  color="gray"
                  size="lg"
                  aria-label={t('playlists.detail.open_ytmusic')}
                >
                  <IconBrandYoutube size={22} />
                </ActionIcon>
              </Tooltip>
            ) : null}
          </Group>
        }
      />

      {isDesktop ? (
        <Flex gap="lg" align="flex-start" wrap="nowrap">
          <PlaylistPlayerPanel playlistId={id} items={tracks} />
          {/* List capped at ~2× the player width (player .root is 442px). */}
          <div style={{ flex: 1, minWidth: 0, maxWidth: 884 }}>{tilesList}</div>
        </Flex>
      ) : (
        tilesList
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
