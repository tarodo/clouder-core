// frontend/src/features/curate/components/CurateSession.tsx
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { ActionIcon, Button, Group, Stack, Text } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { CurateCard, CurateStats } from './CurateCard';
import { DestinationGrid } from './DestinationGrid';
import { HotkeyOverlay } from './HotkeyOverlay';
import { EndOfQueue } from './EndOfQueue';
import { CurateSkeleton } from './CurateSkeleton';
import { useCurateSession } from '../hooks/useCurateSession';
import { useCurateHotkeys } from '../hooks/useCurateHotkeys';
import { useFireTag } from '../hooks/useFireTag';
import { stagingOverflow } from '../lib/destinationMap';
import { IconArrowLeft, IconKeyboard } from '../../../components/icons';
import { bucketLabel, type TriageBucket } from '../../triage/lib/bucketLabels';
import { suggestedDestinations } from '../../triage/lib/suggestedDestinations';
import { usePlayback } from '../../playback/usePlayback';
import { usePlaybackHotkeys } from '../../playback/usePlaybackHotkeys';
import {
  ConnectedPlayerCard,
  TrackCards,
  transportHotkeys,
} from '../../playback/TrackPlayer';
import { spotifyApi } from '../../playback/api/spotifyWebApi';
import { AiRepBadge } from '../../library/components/AiRepBadge';
import { EntityLink } from '../../library/components/EntityLinks';
import { bucketTrackInfo } from '../../triage/lib/toPlaybackTrack';
import { AnalysisMeta } from '../../triage/components/AnalysisMeta';

export interface CurateSessionProps {
  styleId: string;
  blockId: string;
  bucketId: string;
}

export function CurateSession({ styleId, blockId, bucketId }: CurateSessionProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const session = useCurateSession({ styleId, blockId, bucketId });
  const playback = usePlayback();
  const [overlayOpen, setOverlayOpen] = useState(false);
  const fire = useFireTag(session.currentTrack?.track_id ?? null);

  useCurateHotkeys({
    buckets: session.destinations,
    overlayOpen,
    onAssign: session.assign,
    onUndo: session.undo,
    onOpenOverlay: () => setOverlayOpen(true),
    onCloseOverlay: () => setOverlayOpen(false),
    onExit: () => navigate(`/triage/${styleId}/${blockId}`),
    onToggleForce: session.toggleForce,
    onToggleFire: fire.toggle,
  });

  usePlaybackHotkeys(transportHotkeys(playback));

  const allNullSpotifyId =
    playback.queue.tracks.length > 0 &&
    playback.queue.tracks.every((t) => t.spotify_id == null || t.spotify_id === '');

  const baseTrack =
    playback.track.current ??
    playback.queue.tracks[playback.queue.cursor] ??
    null;

  // Cover fallback: backend track.cover_url is sometimes null. play()
  // and advance() pre-fetch the cover from Spotify Web API ON REMOTE
  // devices (where SDK player_state_changed never fires album.images).
  // This effect covers the case BEFORE the user has clicked Play —
  // PlayerCard otherwise sits with no cover for tracks whose
  // backend cover_url is empty. Cache by spotify_id so navigation
  // back to the same track doesn't re-fetch.
  const [coverCache, setCoverCache] = useState<Record<string, string>>({});
  const baseSpotifyId = baseTrack?.spotify_id ?? null;
  const baseCover = baseTrack?.cover_url ?? null;
  useEffect(() => {
    if (baseCover || !baseSpotifyId) return;
    if (coverCache[baseSpotifyId]) return;
    let cancelled = false;
    void spotifyApi
      .getTrackCover(baseSpotifyId)
      .then((url) => {
        if (cancelled || !url) return;
        setCoverCache((prev) =>
          prev[baseSpotifyId] ? prev : { ...prev, [baseSpotifyId]: url },
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [baseSpotifyId, baseCover, coverCache]);

  const playerTrack =
    baseTrack && !baseTrack.cover_url && baseSpotifyId && coverCache[baseSpotifyId]
      ? { ...baseTrack, cover_url: coverCache[baseSpotifyId] ?? null }
      : baseTrack;

  if (session.status === 'loading') return <CurateSkeleton />;
  if (session.status === 'error') {
    return (
      <Stack align="center" p="xl">
        <Text c="red">{t('curate.toast.move_failed')}</Text>
      </Stack>
    );
  }
  if (session.status === 'empty' && session.block) {
    return (
      <EndOfQueue
        styleId={styleId}
        block={session.block}
        currentBucketId={bucketId}
        totalAssigned={session.totalAssigned}
      />
    );
  }
  if (!session.currentTrack || !session.block) return <CurateSkeleton />;

  const currentBucket: TriageBucket | undefined = session.block.buckets.find(
    (b) => b.id === bucketId,
  );
  const currentLabel = currentBucket ? bucketLabel(currentBucket, t) : '';
  // Live remaining count from block.buckets — useMoveTracks decrements
  // track_count optimistically on assign and the block query refetches on
  // success, so this stays accurate without extra accounting.
  const remaining = currentBucket?.track_count ?? 0;
  const counter = t('curate.footer.tracks_left', {
    count: remaining,
    label: currentLabel,
    block: session.block.name,
  });
  const hasOverflow = stagingOverflow(session.destinations).length > 0;

  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        minHeight: '100%',
        display: 'flex',
        justifyContent: 'center',
        // Center the player relative to the viewport, not to AppShell.Main —
        // Main has padding-left = navbar-offset, so without this shift the
        // whole layout slides right by half the navbar width when the side
        // navigation opens. The var is 0 on mobile / when the navbar is
        // hidden, so this is a no-op there.
        transform: 'translateX(calc(-1 * var(--app-shell-navbar-offset) / 2))',
      }}
    >
    <Stack
      gap={isMobile ? 'xs' : 'sm'}
      p={isMobile ? 'sm' : 'md'}
      data-testid="curate-session"
      style={{
        maxWidth: 720,
        width: '100%',
        // Fill the AppShell.Main height so the flex-1 spacer below the card
        // can push the destination strip down to the actual viewport bottom.
        minHeight: '100%',
      }}
    >
      <Group justify="space-between" align="center" gap="xs">
        <ActionIcon
          variant="subtle"
          size="sm"
          aria-label={t('curate.back_aria')}
          onClick={() => navigate(`/triage/${styleId}/${blockId}`)}
        >
          <IconArrowLeft size={16} />
        </ActionIcon>
        <Text size="xs" c="var(--color-fg-muted)">
          {counter}
        </Text>
        <ActionIcon
          variant="subtle"
          size="sm"
          aria-label={t('curate.help_aria')}
          onClick={() => setOverlayOpen(true)}
        >
          <IconKeyboard size={16} />
        </ActionIcon>
      </Group>

      <ConnectedPlayerCard
        emptyBucket={allNullSpotifyId}
        // A phone keeps the text beside the cover to title, artists and label.
        {...(isMobile && { deviceIndicator: null })}
        track={playerTrack}
        mobileSeekChips={isMobile}
        spotifyHref={
          session.currentTrack.spotify_id
            ? `https://open.spotify.com/track/${session.currentTrack.spotify_id}`
            : undefined
        }
        spotifyAriaLabel={t('curate.card.open_in_spotify_aria', {
          title: session.currentTrack.title,
        })}
        mixName={session.currentTrack.mix_name}
        artistLinks={session.currentTrack.artists}
        metaRow={
          <Stack gap={2} mt={4}>
            <Group gap={4} wrap="nowrap" style={{ minWidth: 0 }}>
              <Text size="sm" c="var(--color-fg-muted)">
                {t('curate.card.label_label')}:
              </Text>
              <Text
                size="sm"
                c="var(--color-fg-muted)"
                truncate
                style={{ flex: 1, minWidth: 0 }}
              >
                {session.currentTrack.label_id && session.currentTrack.label_name ? (
                  <EntityLink
                    kind="label"
                    id={session.currentTrack.label_id}
                    name={session.currentTrack.label_name}
                  />
                ) : (
                  (session.currentTrack.label_name ?? '—')
                )}
                <AiRepBadge rep={session.currentTrack.label_ai} ml={4} />
              </Text>
            </Group>
            {/* On a phone the stats go in the card under the player. */}
            {!isMobile && (
              <>
                <CurateStats track={session.currentTrack} />
                <AnalysisMeta
                  aiVerdict={session.currentTrack.ai_verdict}
                  aiChecked={session.currentTrack.ai_checked}
                  profiled={session.currentTrack.profiled}
                />
              </>
            )}
          </Stack>
        }
        topActions={
          <Button
            size="compact-xs"
            color="orange"
            variant={fire.active ? 'filled' : 'default'}
            leftSection={<span aria-hidden>🔥</span>}
            aria-pressed={fire.active}
            disabled={!fire.ready}
            title={t('curate.card.fire_title')}
            onClick={fire.toggle}
          >
            {t('curate.card.fire')}
          </Button>
        }
      />
      {isMobile && (
        <CurateCard
          track={session.currentTrack}
          hideText
          onPlay={() => void playback.controls.play(session.currentIndex)}
        />
      )}
      {/* Flex spacer pushes the destination strip to the bottom of the
          available height. When content overflows (tall card / cramped
          screen), the strip still scrolls naturally. */}
      <div style={{ flex: 1 }} />
      <div
        style={{
          position: 'sticky',
          bottom: 0,
          alignSelf: 'stretch',
          background: 'var(--color-bg)',
          borderTop: '1px solid var(--color-border)',
          paddingTop: 'var(--mantine-spacing-sm)',
          paddingBottom: 'var(--mantine-spacing-sm)',
          // Negative margins extend the background to the page edges
          // so the destination strip reads as "pinned to bottom" rather
          // than a card with gutters.
          marginInline: isMobile
            ? 'calc(-1 * var(--mantine-spacing-sm))'
            : 'calc(-1 * var(--mantine-spacing-md))',
          marginBottom: isMobile
            ? 'calc(-1 * var(--mantine-spacing-sm))'
            : 'calc(-1 * var(--mantine-spacing-md))',
          paddingInline: isMobile
            ? 'var(--mantine-spacing-sm)'
            : 'var(--mantine-spacing-md)',
          zIndex: 1,
        }}
      >
        <DestinationGrid
          buckets={session.destinations}
          currentBucketId={bucketId}
          lastTappedBucketId={session.lastTappedBucketId}
          forceMode={session.forceMode}
          suggested={suggestedDestinations(
            session.currentTrack.prediction,
            session.block.buckets,
          )}
          onAssign={session.assign}
          onToggleForce={session.toggleForce}
        />
      </div>

      <HotkeyOverlay
        opened={overlayOpen}
        onClose={() => setOverlayOpen(false)}
        hasOverflow={hasOverflow}
      />
    </Stack>
    {!isMobile && (
      <Stack
        gap="sm"
        style={{
          position: 'absolute',
          top: 'var(--mantine-spacing-md)',
          left: '50%',
          // Up to the window's right edge, 420px at most. The wrapper is shifted left by half
          // the navbar (see above), so its own right edge stops that much short of the window.
          right: 'calc(var(--mantine-spacing-md) - var(--app-shell-navbar-offset, 0px) / 2)',
          maxWidth: 420,
          marginLeft: 'calc(360px + var(--mantine-spacing-md))',
        }}
      >
        <TrackCards info={bucketTrackInfo(session.currentTrack)} />
      </Stack>
    )}
    </div>
  );
}
