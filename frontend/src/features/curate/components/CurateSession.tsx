// frontend/src/features/curate/components/CurateSession.tsx
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { ActionIcon, Group, Stack, Text } from '@mantine/core';
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
  const [overlayOpen, setOverlayOpen] = useState(false);

  useCurateHotkeys({
    buckets: session.destinations,
    overlayOpen,
    onAssign: session.assign,
    onUndo: session.undo,
    onSkip: session.skip,
    onPrev: session.prev,
    onOpenOverlay: () => setOverlayOpen(true),
    onCloseOverlay: () => setOverlayOpen(false),
    onExit: () => navigate(`/triage/${styleId}/${blockId}`),
    onOpenSpotify: session.openSpotify,
  });

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

      <CurateCard track={session.currentTrack} />
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
