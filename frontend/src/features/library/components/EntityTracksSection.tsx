import { useCallback, useEffect, useMemo, useRef } from 'react';
import { Flex, Stack, Title, useMantineTheme } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { usePlayback } from '../../playback/usePlayback';
import { useBoundQueue } from '../../playback/hooks/useBoundQueue';
import type { PlaybackTrack } from '../../playback/lib/types';
import { useEntityTracks, type EntityKind, type EntityTrack } from '../hooks/useEntityTracks';
import { EntityPlayerPanel } from './EntityPlayerPanel';
import { EntityTrackList } from './EntityTrackList';

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

/**
 * Every CLOUDER track of a label / an artist, newest release first, with a player that drops the
 * playing track into a category or a playlist. Desktop: the player beside the list; phone: above it
 * once something plays. Leaving the page clears the queue, like the other players.
 */
export function EntityTracksSection({ kind, entityId }: { kind: EntityKind; entityId: string }) {
  const { t } = useTranslation();
  const theme = useMantineTheme();
  const isDesktop = useMediaQuery(`(min-width: ${theme.breakpoints.md})`, true);
  const playback = usePlayback();
  const query = useEntityTracks(kind, entityId);
  const top = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void playback.controls.prewarm();
  }, [playback.controls]);

  const items = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);
  const queueTracks = useMemo(() => items.map(toPlaybackTrack), [items]);
  useBoundQueue({ type: 'entity', kind, entityId }, queueTracks);

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

  const total = query.data?.pages[0]?.total;
  const list = (
    <EntityTrackList
      kind={kind}
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
    />
  );

  return (
    <Stack gap="md" ref={top}>
      <Title order={4}>
        {total === undefined
          ? t('library.entity_tracks.title')
          : t('library.entity_tracks.title_count', { count: total })}
      </Title>
      {isDesktop ? (
        <Flex gap="lg" align="flex-start" wrap="nowrap">
          <EntityPlayerPanel kind={kind} entityId={entityId} items={items} />
          <div style={{ flex: 1, minWidth: 0 }}>{list}</div>
        </Flex>
      ) : (
        <>
          {playback.track.current ? (
            <EntityPlayerPanel kind={kind} entityId={entityId} items={items} />
          ) : null}
          {list}
        </>
      )}
    </Stack>
  );
}
