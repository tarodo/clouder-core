import { useCallback, useMemo } from 'react';
import { Button, Divider, SimpleGrid, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { usePlayback } from '../../playback/usePlayback';
import { usePlayerHotkeys } from '../../playback/hooks/usePlayerHotkeys';
import { TrackPlayer, transportHotkeys, usePlayingRow } from '../../playback/TrackPlayer';
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

  const trackId = playback.track.current?.id ?? null;
  // Kept while a new page replaces the list.
  const rich = usePlayingRow(items, (it) => it.id);

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
    ...transportHotkeys(playback),
    onTogglePlaylist: (index) => {
      const pl = playlistsQuery.data?.items[index];
      if (pl) togglePlaylist(pl.id, !playlistIds.includes(pl.id));
    },
    onUndo: () => {},
  });

  const inCategory = new Set(rich?.categories.map((c) => c.id) ?? []);
  const info = rich && {
    mixName: rich.mix_name,
    artists: rich.artists,
    // a label's own page names it already
    label: kind === 'artist' ? rich.label : null,
    bpm: rich.bpm,
    key: { camelot: rich.key_camelot, name: rich.key_name },
    releaseDate: rich.release_date,
  };

  return (
    <TrackPlayer
      className={classes.root}
      info={info}
      empty={t('library.entity_player.pick_track')}
    >
      {(track) => (
        <>
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
            trackId={track.id}
            trackPlaylistIds={playlistIds}
            onAdd={(id) => togglePlaylist(id, true)}
            onRemove={(id) => togglePlaylist(id, false)}
          />
        </>
      )}
    </TrackPlayer>
  );
}
