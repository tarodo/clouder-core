import { useCallback, useEffect, useMemo, useRef } from 'react';
import { Badge, Divider, Group, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { usePlayback } from '../../playback/usePlayback';
import { usePlayerHotkeys } from '../../playback/hooks/usePlayerHotkeys';
import { useTags } from '../../tags';
import { usePlaylistAddTrackTag, usePlaylistRemoveTrackTag } from '../hooks/usePlaylistTrackTag';
import { undoStack, useUndoStack } from '../../categories/hooks/useUndoStack';
import { PlayerCard, type PlayerCardState } from '../../playback/PlayerCard';
import { DeviceIndicator } from '../../playback/DeviceIndicator';
import { PlayerPanelTagCloud } from '../../categories/components/PlayerPanelTagCloud';
import { ArtistsPanel } from '../../library/components/ArtistsPanel';
import { LabelTile } from '../../library/components/LabelTile';
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

  // Rich metadata lookup: find the currently playing track inside `items`.
  // When the playing track is no longer in the list we fall back to the
  // last-seen rich row so the PlayerCard keeps showing label/BPM until
  // playback stops.
  const richTrack = useMemo<PlaylistTrack | null>(() => {
    const id = current?.id;
    if (!id) return null;
    return items.find((it) => it.track_id === id) ?? null;
  }, [items, current?.id]);
  const lastRichRef = useRef<PlaylistTrack | null>(null);
  useEffect(() => {
    if (richTrack) lastRichRef.current = richTrack;
  }, [richTrack]);
  const effectiveRich = richTrack ?? lastRichRef.current;
  // Drop cached rich row when playback stops entirely.
  useEffect(() => {
    if (!current) lastRichRef.current = null;
  }, [current]);

  const assignedTagIds = useMemo<readonly string[]>(
    () => effectiveRich?.tags.map((tg) => tg.id) ?? [],
    [effectiveRich?.tags],
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
  // u undo) — active only while this playlist owns the queue. No playlist-toggle
  // digits here (playlistCount = 0).
  usePlayerHotkeys({
    active:
      playback.queue.source?.type === 'playlist' &&
      playback.queue.source.playlistId === playlistId,
    playlistCount: 0,
    onTogglePlayPause: () => void playback.controls.togglePlayPause(),
    onPrev: () => void playback.controls.prev(),
    onNext: () => void playback.controls.next(),
    onSeekPct: (p) => void playback.controls.seekPct(p),
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

  // Map the queue status to a PlayerCardState.
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
      <LabelTile
        labelId={effectiveRich?.label?.id ?? null}
        labelName={effectiveRich?.label?.name ?? null}
      />
      <ArtistsPanel artists={effectiveRich?.artists ?? []} />
    </Stack>
  );
}
