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
  const total = session.queue.length;
  const counter = t('curate.footer.track_counter', {
    current: session.currentIndex + 1,
    total,
  });
  const hasOverflow = stagingOverflow(session.destinations).length > 0;

  return (
    <Stack gap="md" p={isMobile ? 'sm' : 'xl'} data-testid="curate-session">
      <Group justify="space-between" align="center">
        <ActionIcon
          variant="subtle"
          aria-label={t('curate.back_aria')}
          onClick={() => navigate(`/triage/${styleId}/${blockId}`)}
        >
          <IconArrowLeft size={18} />
        </ActionIcon>
        <Text size="sm" c="var(--color-fg-muted)">
          {counter} {t('curate.footer.in_bucket', { label: currentLabel })}
        </Text>
        <ActionIcon
          variant="subtle"
          aria-label={t('curate.help_aria')}
          onClick={() => setOverlayOpen(true)}
        >
          <IconKeyboard size={18} />
        </ActionIcon>
      </Group>

      <Group
        align="flex-start"
        gap={isMobile ? 'md' : 'xl'}
        wrap={isMobile ? 'wrap' : 'nowrap'}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <CurateCard track={session.currentTrack} />
        </div>
        <div style={{ width: isMobile ? '100%' : 360, flexShrink: 0 }}>
          <DestinationGrid
            buckets={session.destinations}
            currentBucketId={bucketId}
            lastTappedBucketId={session.lastTappedBucketId}
            onAssign={session.assign}
          />
        </div>
      </Group>

      {!isMobile && (
        <Group gap="md" justify="center">
          <Text size="xs" c="var(--color-fg-muted)">
            J {t('curate.footer.shortcut_skip')} · K {t('curate.footer.shortcut_prev')} · U{' '}
            {t('curate.footer.shortcut_undo')} · ? {t('curate.footer.shortcut_help')} · Esc{' '}
            {t('curate.footer.shortcut_exit')}
          </Text>
        </Group>
      )}

      <HotkeyOverlay
        opened={overlayOpen}
        onClose={() => setOverlayOpen(false)}
        hasOverflow={hasOverflow}
      />
    </Stack>
  );
}
