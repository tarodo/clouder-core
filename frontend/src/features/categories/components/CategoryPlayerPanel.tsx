import { useCallback, useEffect, useMemo, useRef } from 'react';
import { Divider, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { usePlayback } from '../../playback/usePlayback';
import { useTags } from '../../tags';
import { useAddTrackTag } from '../../tags/hooks/useAddTrackTag';
import { useRemoveTrackTag } from '../../tags/hooks/useRemoveTrackTag';
import { usePlaylists } from '../../playlists/hooks/usePlaylists';
import { useAddTracksToPlaylist } from '../../playlists/hooks/useAddTracksToPlaylist';
import { useRemoveTrackFromPlaylist } from '../../playlists/hooks/useRemoveTrackFromPlaylist';
import { usePlayerHotkeys } from '../../playback/hooks/usePlayerHotkeys';
import { undoStack, useUndoStack } from '../hooks/useUndoStack';
import { useRemoveTrackOptimistic } from '../hooks/useRemoveTrackOptimistic';
import { useAddTrackToCategory } from '../hooks/useAddTrackToCategory';
import { useTelemetry } from '../../../lib/telemetry/hooks';
import {
  TrackCards,
  TrackPlayer,
  transportHotkeys,
  usePlayingRow,
} from '../../playback/TrackPlayer';
import type { CategoryTrack } from '../hooks/useCategoryTracks';
import { PlayerPanelTagCloud } from './PlayerPanelTagCloud';
import { PlayerPanelPlaylistCloud } from './PlayerPanelPlaylistCloud';
import { CommentsPanel } from '../../playlists/components/CommentsPanel';
import classes from './CategoryPlayerPanel.module.css';

export interface CategoryPlayerPanelProps {
  categoryId: string;
  /**
   * Visible tracks list from the parent page. Used to look up rich metadata
   * (label, BPM, mix_name, AI flag) for the currently playing track so the
   * PlayerCard can render label/BPM and mixName the same way curate does.
   */
  items: CategoryTrack[];
}

const TOAST_ID = 'category-player-undo';

export function CategoryPlayerPanel({ categoryId, items }: CategoryPlayerPanelProps) {
  const { t } = useTranslation();
  const playback = usePlayback();
  const playlistsQuery = usePlaylists({ status: 'active', limit: 100 });
  const tagsQuery = useTags();
  const addTag = useAddTrackTag();
  const removeTag = useRemoveTrackTag();
  const addToPlaylist = useAddTracksToPlaylist();
  const removeFromPlaylist = useRemoveTrackFromPlaylist();
  const removeFromCategory = useRemoveTrackOptimistic();
  const addToCategory = useAddTrackToCategory();
  const telemetry = useTelemetry();
  const { entry } = useUndoStack();
  // One removal at a time: a double Z before the first lands would skip twice.
  const removing = useRef(false);

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

  // Kept while the track drops out of the list (e.g. added to a playlist with fresh-on).
  const row = usePlayingRow(items, (it) => it.id);

  // The playing track's tag and playlist assignments are sourced from the
  // rich CategoryTrack row (which carries `tags`). Playlist membership is
  // not projected today — that stays as an empty list.
  const assignedTagIds = useMemo<readonly string[]>(
    () => row?.tags.map((tg) => tg.id) ?? [],
    [row?.tags],
  );
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
      // Throwing the track into a playlist means we're done with it — advance
      // to the next track so the curator keeps moving without a manual skip.
      void playback.controls.next();
    },
    [trackId, addToPlaylist, removeFromPlaylist, pushUndo, t, playback],
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

  // Z: drop the current track from this category and move on; U puts it back.
  const onRemoveFromCategory = useCallback(async () => {
    if (!trackId || removing.current) return;
    removing.current = true;
    // The row's own values let U put it back in its old place.
    const restore = row
      ? {
          added_at: row.added_at,
          source_triage_block_id: row.source_triage_block_id,
        }
      : undefined;
    try {
      await removeFromCategory.mutateAsync({ categoryId, trackId });
      telemetry.track('track_categorized', {
        track_id: trackId,
        category_key: categoryId,
        action: 'removed_from_category',
      });
      pushUndo(t('categories.toast.track_removed'), async () => {
        await addToCategory.mutateAsync({ categoryId, trackId, restore });
      });
      void playback.controls.next();
    } catch {
      notifications.show({ message: t('categories.toast.track_remove_failed'), color: 'red' });
    } finally {
      removing.current = false;
    }
  }, [
    categoryId,
    trackId,
    row,
    removeFromCategory,
    addToCategory,
    telemetry,
    pushUndo,
    t,
    playback,
  ]);

  const onTogglePlaylistByIndex = useCallback(
    (index: number) => {
      const pl = playlistsQuery.data?.items?.[index];
      if (!pl) return;
      const alreadyIn = trackPlaylistIds.includes(pl.id);
      void (alreadyIn ? onRemovePlaylist(pl.id) : onAddPlaylist(pl.id));
    },
    [playlistsQuery.data, trackPlaylistIds, onAddPlaylist, onRemovePlaylist],
  );

  usePlayerHotkeys({
    active:
      playback.queue.source?.type === 'category' &&
      playback.queue.source.categoryId === categoryId,
    playlistCount: Math.min(10, playlistsQuery.data?.items?.length ?? 0),
    ...transportHotkeys(playback),
    onTogglePlaylist: onTogglePlaylistByIndex,
    onUndo: () => void undoStack.popAndRun(),
    onRemove: () => void onRemoveFromCategory(),
  });

  const info = row && {
    mixName: row.mix_name,
    artists: row.artists,
    label: row.label,
    bpm: row.bpm,
    key: { camelot: row.key_camelot ?? null, name: row.key_name ?? null },
  };

  return (
    <TrackPlayer
      className={classes.root}
      info={info}
      empty={t('category_player.empty.pick_track')}
    >
      {(track) => (
        <>
          <Divider />
          <Text fw={500} size="sm">
            {t('category_player.sections.tags')}
          </Text>
          <PlayerPanelTagCloud
            trackId={track.id}
            assignedTagIds={assignedTagIds}
            onAdd={(id) => void onAddTag(id)}
            onRemove={(id) => void onRemoveTag(id)}
          />
          <Divider />
          <Text fw={500} size="sm">
            {t('category_player.sections.playlists')}
          </Text>
          <PlayerPanelPlaylistCloud
            trackId={track.id}
            trackPlaylistIds={trackPlaylistIds}
            onAdd={(id) => void onAddPlaylist(id)}
            onRemove={(id) => void onRemovePlaylist(id)}
          />
          <TrackCards info={info} />
          <CommentsPanel trackId={track.id} />
        </>
      )}
    </TrackPlayer>
  );
}
