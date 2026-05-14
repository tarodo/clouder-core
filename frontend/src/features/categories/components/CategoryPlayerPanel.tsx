import { useCallback, useEffect, useMemo } from 'react';
import { Divider, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { usePlayback } from '../../playback/usePlayback';
import { useTags } from '../../tags';
import { useAddTrackTag } from '../../tags/hooks/useAddTrackTag';
import { useRemoveTrackTag } from '../../tags/hooks/useRemoveTrackTag';
import { usePlaylists } from '../../playlists/hooks/usePlaylists';
import { useAddTracksToPlaylist } from '../../playlists/hooks/useAddTracksToPlaylist';
import { useRemoveTrackFromPlaylist } from '../../playlists/hooks/useRemoveTrackFromPlaylist';
import { useCategoryPlayerHotkeys } from '../hooks/useCategoryPlayerHotkeys';
import { undoStack, useUndoStack } from '../hooks/useUndoStack';
import { PlayerCard, type PlayerCardState } from '../../playback/PlayerCard';
import { PlayerPanelTagCloud } from './PlayerPanelTagCloud';
import { PlayerPanelPlaylistCloud } from './PlayerPanelPlaylistCloud';
import classes from './CategoryPlayerPanel.module.css';

export interface CategoryPlayerPanelProps {
  categoryId: string;
  styleId: string;
}

const TOAST_ID = 'category-player-undo';

export function CategoryPlayerPanel({ categoryId }: CategoryPlayerPanelProps) {
  const { t } = useTranslation();
  const playback = usePlayback();
  const playlistsQuery = usePlaylists({ status: 'active', limit: 100 });
  const tagsQuery = useTags();
  const addTag = useAddTrackTag();
  const removeTag = useRemoveTrackTag();
  const addToPlaylist = useAddTracksToPlaylist();
  const removeFromPlaylist = useRemoveTrackFromPlaylist();
  const { entry } = useUndoStack();

  const current = playback.track.current;
  const trackId = current?.id ?? null;

  // Tag lookup helper — useAddTrackTag wants the full Tag object (id+name+color)
  // for its optimistic cache patch. Other mutations only need ids.
  const tagsById = useMemo(() => {
    const map = new Map<string, { id: string; name: string; color: string | null }>();
    for (const tg of tagsQuery.data ?? []) {
      map.set(tg.id, { id: tg.id, name: tg.name, color: tg.color });
    }
    return map;
  }, [tagsQuery.data]);

  // The playing track's tag and playlist assignments are sourced by the page
  // that mounts this panel (it has access to the cached CategoryTrack row).
  // For now we render with empty assignments — Task 17 wires the data in.
  const assignedTagIds = useMemo<readonly string[]>(() => [], []);
  const trackPlaylistIds = useMemo<readonly string[]>(() => [], []);

  const pushUndo = useCallback(
    (label: string, undo: () => Promise<void> | void) => {
      undoStack.push({ id: crypto.randomUUID(), label, undo });
      notifications.show({
        id: TOAST_ID,
        message: label,
        autoClose: 8000,
        withCloseButton: true,
      });
    },
    [],
  );

  useEffect(() => {
    if (!entry) notifications.hide(TOAST_ID);
  }, [entry]);

  const onAddTag = useCallback(
    async (tagId: string) => {
      if (!trackId) return;
      const tag = tagsById.get(tagId);
      if (!tag) return;
      await addTag.mutateAsync({ categoryId, trackId, tag });
      pushUndo(t('category_player.toasts.tagged'), () =>
        removeTag.mutateAsync({ categoryId, trackId, tagId }),
      );
    },
    [categoryId, trackId, tagsById, addTag, removeTag, pushUndo, t],
  );

  const onRemoveTag = useCallback(
    async (tagId: string) => {
      if (!trackId) return;
      const tag = tagsById.get(tagId);
      await removeTag.mutateAsync({ categoryId, trackId, tagId });
      pushUndo(t('category_player.toasts.untagged'), () => {
        if (!tag) return;
        return addTag.mutateAsync({ categoryId, trackId, tag });
      });
    },
    [categoryId, trackId, tagsById, addTag, removeTag, pushUndo, t],
  );

  const onAddPlaylist = useCallback(
    async (playlistId: string) => {
      if (!trackId) return;
      await addToPlaylist.mutateAsync({ playlistId, trackIds: [trackId] });
      pushUndo(t('category_player.toasts.added_to_playlist'), () =>
        removeFromPlaylist.mutateAsync({ playlistId, trackId }),
      );
    },
    [trackId, addToPlaylist, removeFromPlaylist, pushUndo, t],
  );

  const onRemovePlaylist = useCallback(
    async (playlistId: string) => {
      if (!trackId) return;
      await removeFromPlaylist.mutateAsync({ playlistId, trackId });
      pushUndo(t('category_player.toasts.removed_from_playlist'), async () => {
        await addToPlaylist.mutateAsync({ playlistId, trackIds: [trackId] });
      });
    },
    [trackId, addToPlaylist, removeFromPlaylist, pushUndo, t],
  );

  const onTogglePlaylistByIndex = useCallback(
    (index: number) => {
      const pl = playlistsQuery.data?.items?.[index];
      if (!pl) return;
      const alreadyIn = trackPlaylistIds.includes(pl.id);
      void (alreadyIn ? onRemovePlaylist(pl.id) : onAddPlaylist(pl.id));
    },
    [playlistsQuery.data, trackPlaylistIds, onAddPlaylist, onRemovePlaylist],
  );

  useCategoryPlayerHotkeys({
    active:
      playback.queue.source?.type === 'category' &&
      playback.queue.source.categoryId === categoryId,
    playlistCount: Math.min(10, playlistsQuery.data?.items?.length ?? 0),
    onTogglePlayPause: () => void playback.controls.togglePlayPause(),
    onPrev: () => void playback.controls.prev(),
    onNext: () => void playback.controls.next(),
    onSeekPct: (p) => void playback.controls.seekPct(p),
    onTogglePlaylist: onTogglePlaylistByIndex,
    onUndo: () => void undoStack.popAndRun(),
  });

  // Map the queue status to a PlayerCardState (the card has a richer state
  // machine including error / disconnected / empty-bucket which the bucket
  // session uses; for category playback we collapse to the basics).
  const playerState: PlayerCardState = (() => {
    if (playback.sdk.error?.kind === 'init') return 'disconnected';
    const status = playback.queue.status;
    if (status === 'error') return 'error';
    if (status === 'idle' || status === 'ended') return 'idle';
    if (status === 'loading' || status === 'buffering') return 'buffering';
    if (status === 'disconnected') return 'disconnected';
    return status; // 'playing' | 'paused'
  })();

  if (!current) {
    return (
      <Stack className={classes.root} gap="md">
        <Text c="dimmed">{t('category_player.empty.pick_track')}</Text>
      </Stack>
    );
  }

  return (
    <Stack className={classes.root} gap="md">
      <PlayerCard
        variant="full"
        state={playerState}
        track={current}
        positionMs={playback.track.positionMs}
        onPlayPause={() => void playback.controls.togglePlayPause()}
        onPrev={() => void playback.controls.prev()}
        onNext={() => void playback.controls.next()}
        onRetry={() => void playback.controls.play()}
        onOpenDevicePicker={() => playback.devices.open(null)}
        onSeekMs={(ms) => void playback.controls.seekMs(ms)}
      />
      <Divider />
      <Text fw={500} size="sm">
        {t('category_player.sections.tags')}
      </Text>
      <PlayerPanelTagCloud
        trackId={current.id}
        assignedTagIds={assignedTagIds}
        onAdd={(id) => void onAddTag(id)}
        onRemove={(id) => void onRemoveTag(id)}
      />
      <Divider />
      <Text fw={500} size="sm">
        {t('category_player.sections.playlists')}
      </Text>
      <PlayerPanelPlaylistCloud
        trackId={current.id}
        trackPlaylistIds={trackPlaylistIds}
        onAdd={(id) => void onAddPlaylist(id)}
        onRemove={(id) => void onRemovePlaylist(id)}
      />
    </Stack>
  );
}
