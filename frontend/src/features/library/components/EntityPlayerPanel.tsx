import { useCallback, useEffect, useMemo, useRef } from 'react';
import { Button, Divider, Group, SimpleGrid, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { usePlayback } from '../../playback/usePlayback';
import { usePlayerHotkeys } from '../../playback/hooks/usePlayerHotkeys';
import { PlayerCard, type PlayerCardState } from '../../playback/PlayerCard';
import { DeviceIndicator } from '../../playback/DeviceIndicator';
import { TrackKey } from '../../playback/TrackKey';
import { useCategoriesByStyle } from '../../categories/hooks/useCategoriesByStyle';
import { useAddTrackToCategory } from '../../categories/hooks/useAddTrackToCategory';
import { useRemoveTrackOptimistic } from '../../categories/hooks/useRemoveTrackOptimistic';
import { PlayerPanelPlaylistCloud } from '../../categories/components/PlayerPanelPlaylistCloud';
import { usePlaylists } from '../../playlists/hooks/usePlaylists';
import { useAddTracksToPlaylist } from '../../playlists/hooks/useAddTracksToPlaylist';
import { useRemoveTrackFromPlaylist } from '../../playlists/hooks/useRemoveTrackFromPlaylist';
import {
  patchEntityTrack,
  type EntityKind,
  type EntityTrack,
  type NamedRef,
} from '../hooks/useEntityTracks';
import classes from './EntityPlayerPanel.module.css';

export interface EntityPlayerPanelProps {
  kind: EntityKind;
  entityId: string;
  /** The loaded tracks: the playing one's row carries its style, categories and playlists. */
  items: EntityTrack[];
}

type Field = 'categories' | 'playlists';

const without = (refs: NamedRef[], id: string) => refs.filter((r) => r.id !== id);

/**
 * The player of a label's / an artist's page. A track goes straight into a category of its own
 * style (the suggestion model learns per style) and into any active playlist; a second tap takes
 * it out again.
 */
export function EntityPlayerPanel({ kind, entityId, items }: EntityPlayerPanelProps) {
  const { t } = useTranslation();
  const playback = usePlayback();
  const qc = useQueryClient();
  const addToCategory = useAddTrackToCategory();
  const removeFromCategory = useRemoveTrackOptimistic();
  const addToPlaylist = useAddTracksToPlaylist();
  const removeFromPlaylist = useRemoveTrackFromPlaylist();
  const playlistsQuery = usePlaylists({ status: 'active', limit: 100 });

  const current = playback.track.current;
  const trackId = current?.id ?? null;
  // The playing row; the last one seen while a new page replaces the list.
  const row = useMemo(() => items.find((it) => it.id === trackId) ?? null, [items, trackId]);
  const lastRow = useRef<EntityTrack | null>(null);
  useEffect(() => {
    if (row || !current) lastRow.current = row;
  }, [row, current]);
  const rich = row ?? lastRow.current;

  const style = rich?.style ?? null;
  const categoriesQuery = useCategoriesByStyle(style?.id ?? '');
  const categories = categoriesQuery.data?.items ?? [];

  // Optimistic: the row shows the change at once and gets it back if the call fails.
  const toggle = useCallback(
    async (field: Field, ref: NamedRef, add: boolean) => {
      if (!trackId) return;
      const apply = (on: boolean) =>
        patchEntityTrack(qc, trackId, (tr) => ({
          ...tr,
          [field]: on ? [...without(tr[field], ref.id), ref] : without(tr[field], ref.id),
        }));
      apply(add);
      try {
        if (field === 'categories') {
          await (add
            ? addToCategory.mutateAsync({ categoryId: ref.id, trackId })
            : removeFromCategory.mutateAsync({ categoryId: ref.id, trackId }));
        } else {
          await (add
            ? addToPlaylist.mutateAsync({ playlistId: ref.id, trackIds: [trackId] })
            : removeFromPlaylist.mutateAsync({ playlistId: ref.id, trackId }));
        }
      } catch {
        apply(!add);
        notifications.show({ message: t('library.entity_player.save_failed'), color: 'red' });
      }
    },
    [trackId, qc, addToCategory, removeFromCategory, addToPlaylist, removeFromPlaylist, t],
  );

  const playlistIds = useMemo(() => rich?.playlists.map((p) => p.id) ?? [], [rich?.playlists]);
  const togglePlaylist = useCallback(
    (playlistId: string, add: boolean) => {
      const pl = playlistsQuery.data?.items.find((p) => p.id === playlistId);
      if (pl) void toggle('playlists', { id: pl.id, name: pl.name }, add);
    },
    [playlistsQuery.data, toggle],
  );

  usePlayerHotkeys({
    active:
      playback.queue.source?.type === 'entity' &&
      playback.queue.source.kind === kind &&
      playback.queue.source.entityId === entityId,
    playlistCount: Math.min(10, playlistsQuery.data?.items.length ?? 0),
    onTogglePlayPause: () => void playback.controls.togglePlayPause(),
    onPrev: () => void playback.controls.prev(),
    onNext: () => void playback.controls.next(),
    onSeekRelative: (delta) => void playback.controls.seekMs(playback.track.positionMs + delta),
    onSeekPct: (p) => void playback.controls.seekPct(p),
    onTogglePlaylist: (index) => {
      const pl = playlistsQuery.data?.items[index];
      if (pl) togglePlaylist(pl.id, !playlistIds.includes(pl.id));
    },
    onUndo: () => {},
  });

  const playerState: PlayerCardState = (() => {
    if (playback.sdk.error?.kind === 'init') return 'disconnected';
    const status = playback.queue.status;
    if (status === 'error') return 'error';
    if (status === 'idle' || status === 'ended') return 'idle';
    if (status === 'loading' || status === 'buffering') return 'buffering';
    if (status === 'disconnected') return 'disconnected';
    return status;
  })();

  if (!current) {
    return (
      <Stack className={classes.root} gap="md" data-entity-player>
        <Text c="dimmed">{t('library.entity_player.pick_track')}</Text>
      </Stack>
    );
  }

  const inCategory = new Set(rich?.categories.map((c) => c.id) ?? []);
  const meta = rich ? (
    <Group gap="md" wrap="wrap" mt={4}>
      {kind === 'artist' && rich.label ? (
        <Text size="sm" c="var(--color-fg-muted)" truncate maw="100%">
          {t('curate.card.label_label')}: {rich.label.name}
        </Text>
      ) : null}
      {rich.bpm != null ? (
        <Text size="sm" c="var(--color-fg-muted)" className="font-mono">
          {rich.bpm} BPM
        </Text>
      ) : null}
      <TrackKey camelot={rich.key_camelot} name={rich.key_name} size="sm" />
      {rich.release_date ? (
        <Text size="sm" c="var(--color-fg-muted)" className="font-mono">
          {rich.release_date}
        </Text>
      ) : null}
    </Group>
  ) : null;

  return (
    <Stack className={classes.root} gap="md" data-entity-player>
      <PlayerCard
        variant="full"
        state={playerState}
        track={current}
        positionMs={playback.track.positionMs}
        mixName={rich?.mix_name ?? null}
        belowMainRow={meta}
        showTimes
        spotifyHref={
          current.spotify_id ? `https://open.spotify.com/track/${current.spotify_id}` : undefined
        }
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
        {style
          ? t('library.entity_player.categories', { style: style.name })
          : t('library.entity_player.categories_title')}
      </Text>
      {!style ? (
        <Text c="dimmed" size="sm">
          {t('library.entity_player.no_style')}
        </Text>
      ) : categoriesQuery.isSuccess && categories.length === 0 ? (
        <Text c="dimmed" size="sm">
          {t('library.entity_player.no_categories', { style: style.name })}
        </Text>
      ) : (
        <SimpleGrid cols={2} spacing="xs" verticalSpacing="xs">
          {categories.map((c) => {
            const on = inCategory.has(c.id);
            return (
              <Button
                key={c.id}
                fullWidth
                size="sm"
                variant={on ? 'filled' : 'default'}
                aria-pressed={on}
                onClick={() => void toggle('categories', { id: c.id, name: c.name }, !on)}
                styles={{ label: { whiteSpace: 'normal' }, inner: { justifyContent: 'flex-start' } }}
              >
                {c.name}
              </Button>
            );
          })}
        </SimpleGrid>
      )}
      <Divider />
      <Text fw={500} size="sm">
        {t('category_player.sections.playlists')}
      </Text>
      <PlayerPanelPlaylistCloud
        trackId={current.id}
        trackPlaylistIds={playlistIds}
        onAdd={(id) => togglePlaylist(id, true)}
        onRemove={(id) => togglePlaylist(id, false)}
      />
    </Stack>
  );
}
