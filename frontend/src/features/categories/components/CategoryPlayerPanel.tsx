import { useCallback, useEffect, useMemo, useRef } from 'react';
import { Badge, Divider, Group, Stack, Text } from '@mantine/core';
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
import { DeviceIndicator } from '../../playback/DeviceIndicator';
import type { CategoryTrack } from '../hooks/useCategoryTracks';
import { PlayerPanelTagCloud } from './PlayerPanelTagCloud';
import { PlayerPanelPlaylistCloud } from './PlayerPanelPlaylistCloud';
import { LabelTile } from '../../library/components/LabelTile';
import classes from './CategoryPlayerPanel.module.css';

export interface CategoryPlayerPanelProps {
  categoryId: string;
  styleId: string;
  /**
   * Visible tracks list from the parent page. Used to look up rich metadata
   * (label, BPM, mix_name, AI flag) for the currently playing track so the
   * PlayerCard can render label/BPM and mixName the same way curate does.
   */
  items: CategoryTrack[];
}

const TOAST_ID = 'category-player-undo';

export function CategoryPlayerPanel({ categoryId, styleId, items }: CategoryPlayerPanelProps) {
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

  // Rich metadata lookup: find the currently playing track inside `items`.
  // When the playing track was just shrunk out of the list (e.g. assigned to
  // a playlist with fresh-on), we fall back to the last-seen rich row so the
  // PlayerCard keeps showing label/BPM until natural-end → next track.
  const richTrack = useMemo<CategoryTrack | null>(() => {
    const id = current?.id;
    if (!id) return null;
    return items.find((it) => it.id === id) ?? null;
  }, [items, current?.id]);
  const lastRichRef = useRef<CategoryTrack | null>(null);
  useEffect(() => {
    if (richTrack) lastRichRef.current = richTrack;
  }, [richTrack]);
  const effectiveRich = richTrack ?? lastRichRef.current;
  // Drop the cached rich row when playback stops entirely so the empty state
  // doesn't show metadata from the previous session.
  useEffect(() => {
    if (!current) lastRichRef.current = null;
  }, [current]);

  // The playing track's tag and playlist assignments are sourced from the
  // rich CategoryTrack row (which carries `tags`). Playlist membership is
  // not projected today — that stays as an empty list.
  const assignedTagIds = useMemo<readonly string[]>(
    () => effectiveRich?.tags.map((tg) => tg.id) ?? [],
    [effectiveRich?.tags],
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

  const spotifyHref = current.spotify_id
    ? `https://open.spotify.com/track/${current.spotify_id}`
    : undefined;

  const metaRow =
    effectiveRich != null ? (
      <Stack gap={2} mt={4}>
        {effectiveRich.is_ai_suspected && (
          <Badge
            color="yellow"
            variant="light"
            size="sm"
            style={{ alignSelf: 'flex-start' }}
          >
            {t('curate.card.ai_badge')}
          </Badge>
        )}
        <Group gap="md" wrap="wrap" style={{ minWidth: 0 }}>
          {effectiveRich.label?.name ? (
            <Group gap={4} wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
              <Text size="sm" c="var(--color-fg-muted)">
                {t('curate.card.label_label')}:
              </Text>
              <Text size="sm" c="var(--color-fg-muted)" truncate style={{ flex: 1 }}>
                {effectiveRich.label.name}
              </Text>
            </Group>
          ) : null}
          {effectiveRich.bpm != null ? (
            <Text size="sm" c="var(--color-fg-muted)" className="font-mono">
              {effectiveRich.bpm} BPM
            </Text>
          ) : null}
        </Group>
      </Stack>
    ) : null;

  return (
    <Stack className={classes.root} gap="md">
      <PlayerCard
        variant="full"
        state={playerState}
        track={current}
        positionMs={playback.track.positionMs}
        mixName={effectiveRich?.mix_name ?? null}
        belowMainRow={metaRow}
        showTimes
        spotifyHref={spotifyHref}
        spotifyAriaLabel={t('category_player.actions.open_in_spotify_aria', {
          title: current.title,
        })}
        deviceIndicator={
          <DeviceIndicator
            mode="full"
            active={playback.devices.active}
            cloderTabId={playback.devices.cloderTabId}
            onOpen={(anchor) => playback.devices.open(anchor)}
          />
        }
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
      {effectiveRich?.label?.id && (
        <LabelTile
          labelId={effectiveRich.label.id}
          labelName={effectiveRich.label.name ?? null}
          styleId={styleId}
        />
      )}
    </Stack>
  );
}
