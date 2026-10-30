import { useCallback, useEffect, useMemo } from 'react';
import { Divider, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { usePlayback } from '../../playback/usePlayback';
import { usePlayerHotkeys } from '../../playback/hooks/usePlayerHotkeys';
import { useTags } from '../../tags';
import { usePlaylistAddTrackTag, usePlaylistRemoveTrackTag } from '../hooks/usePlaylistTrackTag';
import { undoStack, useUndoStack } from '../../categories/hooks/useUndoStack';
import {
  TrackCards,
  TrackPlayer,
  transportHotkeys,
  usePlayingRow,
} from '../../playback/TrackPlayer';
import { PlayerPanelTagCloud } from '../../categories/components/PlayerPanelTagCloud';
import { CommentsPanel } from './CommentsPanel';
import type { PlaylistTrack } from '../lib/playlistTypes';
import classes from './PlaylistPlayerPanel.module.css';

export interface PlaylistPlayerPanelProps {
  playlistId: string;
  /**
   * Visible tracks list from the parent page. Used to look up rich metadata
   * (label, BPM, mix_name, AI flag) for the currently playing track so the
   * PlayerCard can render label/BPM and mixName correctly.
   */
  items: PlaylistTrack[];
}

const TOAST_ID = 'playlist-player-undo';

export function PlaylistPlayerPanel({ playlistId, items }: PlaylistPlayerPanelProps) {
  const { t } = useTranslation();
  const playback = usePlayback();
  const tagsQuery = useTags();
  const addTag = usePlaylistAddTrackTag(playlistId);
  const removeTag = usePlaylistRemoveTrackTag(playlistId);
  const { entry } = useUndoStack();

  const current = playback.track.current;
  const trackId = current?.id ?? null;

  // Tag lookup helper — usePlaylistAddTrackTag wants the full tag object
  // (id+name+color) for its optimistic cache patch. Resolve id → full tag here.
  const tagsById = useMemo(() => {
    const map = new Map<string, { id: string; name: string; color: string | null }>();
    for (const tg of tagsQuery.data ?? []) {
      map.set(tg.id, { id: tg.id, name: tg.name, color: tg.color });
    }
    return map;
  }, [tagsQuery.data]);

  const row = usePlayingRow(items, (it) => it.track_id);

  const assignedTagIds = useMemo<readonly string[]>(
    () => row?.tags.map((tg) => tg.id) ?? [],
    [row?.tags],
  );

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

  // Player transport hotkeys (Space play/pause, a/s/d/f/g seek, j/k prev/next,
  // Shift+J/K seek -10s/+10s, u undo) — active only while this playlist owns the
  // queue. No playlist-toggle digits here (playlistCount = 0).
  usePlayerHotkeys({
    active:
      playback.queue.source?.type === 'playlist' &&
      playback.queue.source.playlistId === playlistId,
    playlistCount: 0,
    ...transportHotkeys(playback),
    onTogglePlaylist: () => {},
    onUndo: () => void undoStack.popAndRun(),
  });

  // SEAM FIX: PlayerPanelTagCloud.onAdd gives a tag id only; resolve to full
  // tag before calling usePlaylistAddTrackTag which needs id+name+color for
  // optimistic cache patching.
  const onAddTag = useCallback(
    async (tagId: string) => {
      if (!trackId) return;
      const tag = tagsById.get(tagId);
      if (!tag) return;
      await addTag.mutateAsync({ trackId, tag });
      pushUndo(t('category_player.toasts.tagged'), () =>
        removeTag.mutateAsync({ trackId, tagId }),
      );
    },
    [trackId, tagsById, addTag, removeTag, pushUndo, t],
  );

  const onRemoveTag = useCallback(
    async (tagId: string) => {
      if (!trackId) return;
      const tag = tagsById.get(tagId);
      await removeTag.mutateAsync({ trackId, tagId });
      pushUndo(t('category_player.toasts.untagged'), () => {
        if (!tag) return;
        return addTag.mutateAsync({ trackId, tag });
      });
    },
    [trackId, tagsById, addTag, removeTag, pushUndo, t],
  );

  const info = row && {
    mixName: row.mix_name,
    artists: row.artists,
    label: row.label,
    bpm: row.bpm,
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
          <TrackCards info={info} />
          <CommentsPanel trackId={track.id} />
        </>
      )}
    </TrackPlayer>
  );
}
