import { useCallback, useEffect, useMemo, useRef, type ReactNode } from 'react';
import { Flex, Group, SegmentedControl, Stack, Text, Title, useMantineTheme } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import type { InfiniteData, UseInfiniteQueryResult } from '@tanstack/react-query';
import { useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { usePlayback } from '../../playback/usePlayback';
import { useBoundQueue } from '../../playback/hooks/useBoundQueue';
import type { PlaybackTrack, QueueSource } from '../../playback/lib/types';
import { useArtistSimilar } from '../../similar/useSimilarTracks';
import {
  useEntityTracks,
  type EntityKind,
  type EntityTrack,
  type EntityTracksPage,
} from '../hooks/useEntityTracks';
import { EntityPlayerPanel } from './EntityPlayerPanel';
import { EntityTrackList } from './EntityTrackList';

export type EntitySource = Extract<QueueSource, { type: 'entity' }>;

function toPlaybackTrack(t: EntityTrack): PlaybackTrack {
  return {
    id: t.id,
    title: t.title,
    artists: t.artists.map((a) => a.name).join(', '),
    duration_ms: t.length_ms ?? 0,
    spotify_id: t.spotify_id,
    cover_url: null,
    ai_verdict: t.ai_verdict ?? null,
  };
}

export interface TracksSectionProps {
  /** The queue the list plays as; the player's hotkeys work while it is the playing one. */
  source: EntitySource;
  query: UseInfiniteQueryResult<InfiniteData<EntityTracksPage>>;
  /** The label column and the label in the player: the tracks come from many labels. */
  showLabel: boolean;
  /** The style column; off for a one-style list (similar tracks). */
  showStyle?: boolean;
  title?: ReactNode;
  headerExtra?: ReactNode;
  /** In place of the list when it comes back empty. */
  empty?: ReactNode;
}

/**
 * A list of tracks with a player that drops the playing track into a category or a playlist: a
 * label's / an artist's tracks, or similar ones. Desktop: the player beside the list; phone: above
 * it once something plays. Leaving the page clears the queue, like the other players.
 */
export function TracksSection({
  source,
  query,
  showLabel,
  showStyle,
  title,
  headerExtra,
  empty,
}: TracksSectionProps) {
  const theme = useMantineTheme();
  const isDesktop = useMediaQuery(`(min-width: ${theme.breakpoints.md})`, true);
  const playback = usePlayback();
  const top = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void playback.controls.prewarm();
  }, [playback.controls]);

  const items = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);
  const queueTracks = useMemo(() => items.map(toPlaybackTrack), [items]);
  useBoundQueue(source, queueTracks);

  const play = useCallback(
    (track: EntityTrack) => {
      if (!track.spotify_id) return;
      void playback.controls.prewarm();
      const idx = playback.queue.tracks.findIndex((q) => q.id === track.id);
      void (idx >= 0
        ? playback.controls.play(idx)
        : playback.controls.play(undefined, toPlaybackTrack(track)));
      // phone: the player sits above the list, bring it into view
      if (!isDesktop) top.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    },
    [playback.controls, playback.queue.tracks, isDesktop],
  );

  const list = (
    <EntityTrackList
      showLabel={showLabel}
      showStyle={showStyle}
      items={items}
      variant={isDesktop ? 'desktop' : 'mobile'}
      loading={query.isPending}
      hasMore={!!query.hasNextPage}
      loadingMore={query.isFetchingNextPage}
      onMore={() => void query.fetchNextPage()}
      currentTrackId={playback.track.current?.id ?? null}
      playing={playback.queue.status === 'playing'}
      onPlay={play}
      onToggle={() => void playback.controls.togglePlayPause()}
      empty={empty}
    />
  );
  const panel = <EntityPlayerPanel source={source} showLabel={showLabel} items={items} />;

  return (
    <Stack gap="md" ref={top}>
      {title || headerExtra ? (
        <Group gap="md" wrap="wrap">
          {title ? <Title order={4}>{title}</Title> : null}
          {headerExtra}
        </Group>
      ) : null}
      {isDesktop ? (
        <Flex gap="lg" align="flex-start" wrap="nowrap">
          {panel}
          <div style={{ flex: 1, minWidth: 0 }}>{list}</div>
        </Flex>
      ) : (
        <>
          {playback.track.current ? panel : null}
          {list}
        </>
      )}
    </Stack>
  );
}

function EntityList({
  kind,
  entityId,
  headerExtra,
}: {
  kind: EntityKind;
  entityId: string;
  headerExtra?: ReactNode;
}) {
  const { t } = useTranslation();
  const query = useEntityTracks(kind, entityId);
  const total = query.data?.pages[0]?.total;
  return (
    <TracksSection
      source={{ type: 'entity', kind, entityId }}
      query={query}
      // a label's own page names it already
      showLabel={kind === 'artist'}
      title={
        total === undefined
          ? t('library.entity_tracks.title')
          : t('library.entity_tracks.title_count', { count: total })
      }
      headerExtra={headerExtra}
    />
  );
}

/** The tracks nearest the artist's sound, in one of its styles (a picker when it has several). */
function ArtistSimilar({ artistId, headerExtra }: { artistId: string; headerExtra: ReactNode }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const styleId = params.get('style');
  const query = useArtistSimilar(artistId, styleId);
  const body = query.data?.pages[0];
  const styles = body?.styles ?? [];
  const picker =
    styles.length > 1 ? (
      <SegmentedControl
        size="xs"
        value={body?.style?.id ?? ''}
        data={styles.map((s) => ({ value: s.id, label: s.name }))}
        onChange={(v) =>
          setParams(
            (p) => {
              const next = new URLSearchParams(p);
              next.set('style', v);
              return next;
            },
            { replace: true },
          )
        }
      />
    ) : null;
  return (
    <TracksSection
      source={{ type: 'entity', kind: 'similar', entityId: `artist:${artistId}:${styleId ?? ''}` }}
      query={query}
      showLabel
      showStyle={false}
      title={t('similar.title')}
      headerExtra={
        <>
          {headerExtra}
          {picker}
        </>
      }
      empty={
        <Text c="dimmed">
          {body && !body.profiled ? t('similar.artist_unprofiled') : t('similar.none')}
        </Text>
      }
    />
  );
}

/** An artist's tracks, or (the URL's `?view=similar`) the tracks that sound like the artist. */
function ArtistSection({ artistId }: { artistId: string }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const similar = params.get('view') === 'similar';
  const views = (
    <SegmentedControl
      size="xs"
      value={similar ? 'similar' : 'tracks'}
      data={[
        { value: 'tracks', label: t('similar.view_tracks') },
        { value: 'similar', label: t('similar.view_similar') },
      ]}
      onChange={(v) =>
        setParams(
          (p) => {
            const next = new URLSearchParams(p);
            next.delete('style');
            if (v === 'similar') next.set('view', 'similar');
            else next.delete('view');
            return next;
          },
          { replace: true },
        )
      }
    />
  );
  return similar ? (
    <ArtistSimilar artistId={artistId} headerExtra={views} />
  ) : (
    <EntityList kind="artist" entityId={artistId} headerExtra={views} />
  );
}

/** Every CLOUDER track of a label / an artist, newest release first; an artist's also "Similar". */
export function EntityTracksSection({ kind, entityId }: { kind: EntityKind; entityId: string }) {
  return kind === 'artist' ? (
    <ArtistSection artistId={entityId} />
  ) : (
    <EntityList kind={kind} entityId={entityId} />
  );
}
