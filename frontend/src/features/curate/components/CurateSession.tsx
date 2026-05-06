// frontend/src/features/curate/components/CurateSession.tsx
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { ActionIcon, Badge, Group, Stack, Text } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { CurateCard } from './CurateCard';
import { DestinationGrid } from './DestinationGrid';
import { HotkeyOverlay } from './HotkeyOverlay';
import { EndOfQueue } from './EndOfQueue';
import { CurateSkeleton } from './CurateSkeleton';
import { useCurateSession } from '../hooks/useCurateSession';
import { useCurateHotkeys } from '../hooks/useCurateHotkeys';
import { stagingOverflow } from '../lib/destinationMap';
import { IconArrowLeft, IconKeyboard } from '../../../components/icons';
import { bucketLabel, type TriageBucket } from '../../triage/lib/bucketLabels';
import { usePlayback } from '../../playback/usePlayback';
import { usePlaybackHotkeys } from '../../playback/usePlaybackHotkeys';
import { PlayerCard, type PlayerCardState } from '../../playback/PlayerCard';

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

  useCurateHotkeys({
    buckets: session.destinations,
    overlayOpen,
    onAssign: session.assign,
    onUndo: session.undo,
    onOpenOverlay: () => setOverlayOpen(true),
    onCloseOverlay: () => setOverlayOpen(false),
    onExit: () => navigate(`/triage/${styleId}/${blockId}`),
  });

  usePlaybackHotkeys({
    onTogglePlayPause: () => void playback.controls.togglePlayPause(),
    onPrev: () => void playback.controls.prev(),
    onNext: () => void playback.controls.next(),
    onSeekRelative: (delta) =>
      void playback.controls.seekMs(playback.track.positionMs + delta),
    onSeekPct: (p) => void playback.controls.seekPct(p),
  });

  const allNullSpotifyId =
    playback.queue.tracks.length > 0 &&
    playback.queue.tracks.every((t) => t.spotify_id == null || t.spotify_id === '');

  const playerState: PlayerCardState = (() => {
    if (allNullSpotifyId) return 'empty-bucket';
    if (playback.sdk.error?.kind === 'init') return 'disconnected';
    const status = playback.queue.status;
    if (status === 'error') return 'error';
    if (status === 'idle' || status === 'ended') return 'idle';
    if (status === 'loading' || status === 'buffering') return 'buffering';
    return status; // 'playing' | 'paused'
  })();

  const playerTrack =
    playback.track.current ??
    playback.queue.tracks[playback.queue.cursor] ??
    null;

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
    <Stack
      gap="sm"
      p={isMobile ? 'sm' : 'md'}
      data-testid="curate-session"
      style={{
        maxWidth: 720,
        width: '100%',
        margin: '0 auto',
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

      <PlayerCard
        variant="full"
        state={playerState}
        track={playerTrack}
        positionMs={playback.track.positionMs}
        showText={!isMobile}
        mobileSeekChips={isMobile}
        spotifyHref={
          session.currentTrack.spotify_id
            ? `https://open.spotify.com/track/${session.currentTrack.spotify_id}`
            : undefined
        }
        spotifyAriaLabel={t('curate.card.open_in_spotify_aria', {
          title: session.currentTrack.title,
        })}
        mixName={!isMobile ? session.currentTrack.mix_name : undefined}
        metaRow={
          !isMobile ? (
            <Stack gap={2} mt={4}>
              {session.currentTrack.is_ai_suspected && (
                <Badge
                  color="yellow"
                  variant="light"
                  size="sm"
                  aria-label={t('curate.card.ai_badge_aria')}
                  style={{ alignSelf: 'flex-start' }}
                >
                  {t('curate.card.ai_badge')}
                </Badge>
              )}
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
                  {session.currentTrack.label_name ?? '—'}
                </Text>
              </Group>
              <Group gap="md" wrap="wrap">
                <Group gap={4} wrap="nowrap">
                  <Text size="sm" c="var(--color-fg-muted)">
                    {t('curate.card.bpm_label')}:
                  </Text>
                  <Text size="sm" c="var(--color-fg-muted)">
                    {session.currentTrack.bpm ?? '—'}
                  </Text>
                </Group>
                {session.currentTrack.length_ms != null && (
                  <Group gap={4} wrap="nowrap">
                    <Text size="sm" c="var(--color-fg-muted)">
                      {t('curate.card.length_label')}:
                    </Text>
                    <Text size="sm" c="var(--color-fg-muted)">
                      {(() => {
                        const total = Math.round((session.currentTrack.length_ms ?? 0) / 1000);
                        const m = Math.floor(total / 60);
                        const s = total % 60;
                        return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
                      })()}
                    </Text>
                  </Group>
                )}
                <Group gap={4} wrap="nowrap">
                  <Text size="sm" c="var(--color-fg-muted)">
                    {t('curate.card.released_label')}:
                  </Text>
                  <Text size="sm" c="var(--color-fg-muted)">
                    {session.currentTrack.spotify_release_date ??
                      session.currentTrack.publish_date ??
                      '—'}
                  </Text>
                </Group>
              </Group>
            </Stack>
          ) : undefined
        }
        onPlayPause={() => void playback.controls.togglePlayPause()}
        onPrev={() => void playback.controls.prev()}
        onNext={() => void playback.controls.next()}
        onRetry={() => void playback.controls.play()}
        onOpenDevicePicker={() => {
          /* F7 */
        }}
        onSeekMs={(ms) => void playback.controls.seekMs(ms)}
      />
      {isMobile && (
        <CurateCard
          track={session.currentTrack}
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
          onAssign={session.assign}
        />
      </div>

      <HotkeyOverlay
        opened={overlayOpen}
        onClose={() => setOverlayOpen(false)}
        hasOverflow={hasOverflow}
      />
    </Stack>
  );
}
