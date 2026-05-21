import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Anchor, Button, Flex, Group, Stack, Text, Title, useMantineTheme } from '@mantine/core';
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks';
import { Link, Navigate, Outlet, useMatch, useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { ApiError } from '../../../api/error';
import { EmptyState } from '../../../components/EmptyState';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { IconArrowsExchange } from '../../../components/icons';
import { useTriageBlock } from '../hooks/useTriageBlock';
import {
  takeSnapshot,
  undoMoveDirect,
  useMoveTracks,
  type MoveInput,
  type MoveSnapshot,
} from '../hooks/useMoveTracks';
import { useBucketTracks, type BucketTrack } from '../hooks/useBucketTracks';
import { BucketTracksList } from '../components/BucketTracksList';
import { TransferModal } from '../components/TransferModal';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';
import { useBucketPlayerQueue } from '../hooks/useBucketPlayerQueue';
import { toPlaybackTrack } from '../lib/toPlaybackTrack';
import { usePlayback } from '../../playback/usePlayback';
import { BucketPlayerPanel } from '../components/BucketPlayerPanel';
import type { BucketDetailOutletContext } from './BucketPlayerPage';
import type { PlaybackTrack } from '../../playback/lib/types';

const EMPTY_TRACKS: PlaybackTrack[] = [];

export function BucketDetailPage() {
  const { styleId, id, bucketId } = useParams<{
    styleId: string;
    id: string;
    bucketId: string;
  }>();
  if (!styleId || !id || !bucketId) return <Navigate to="/triage" replace />;
  return <BucketDetailInner styleId={styleId} blockId={id} bucketId={bucketId} />;
}

interface InnerProps {
  styleId: string;
  blockId: string;
  bucketId: string;
}

function BucketDetailInner({ styleId, blockId, bucketId }: InnerProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: block, isLoading, isError, error } = useTriageBlock(blockId);
  const move = useMoveTracks(blockId, styleId);
  const undoInflight = useRef(false);
  const [transferTrackId, setTransferTrackId] = useState<string | null>(null);
  const [rawSearch, setRawSearch] = useState('');
  const [debouncedSearch] = useDebouncedValue(rawSearch.trim(), 300);
  const tracksQuery = useBucketTracks(blockId, bucketId, '');
  const [bulkTransferOpen, setBulkTransferOpen] = useState(false);
  const [bulkTrackIds, setBulkTrackIds] = useState<string[] | null>(null);
  const [collecting, setCollecting] = useState(false);

  const isStagingBucket =
    block?.buckets.find((b) => b.id === bucketId)?.bucket_type === 'STAGING';

  // Playback wiring — all hooks BEFORE early returns (Rules of Hooks)
  const navigate = useNavigate();
  const playback = usePlayback();
  const theme = useMantineTheme();
  const isDesktop = useMediaQuery(`(min-width: ${theme.breakpoints.md})`);
  const onPlayerSubpath = useMatch({
    path: '/triage/:styleId/:id/buckets/:bucketId/player',
    end: false,
  });

  const playerQuery = useBucketTracks(blockId, bucketId, debouncedSearch);
  const playerItems = useMemo(
    () => playerQuery.data?.pages.flatMap((p) => p.items) ?? [],
    [playerQuery.data],
  );
  const playerTracks = useMemo(() => playerItems.map(toPlaybackTrack), [playerItems]);
  useBucketPlayerQueue(blockId, bucketId, isStagingBucket ? playerTracks : EMPTY_TRACKS);

  useEffect(() => {
    void playback.controls.prewarm();
  }, [playback.controls]);

  const playTrack = useCallback(
    (tr: BucketTrack) => {
      if (!isStagingBucket) return;
      if (!tr.spotify_id) return;
      void playback.controls.prewarm();
      const queueIdx = playback.queue.tracks.findIndex((q) => q.id === tr.track_id);
      if (queueIdx >= 0) {
        void playback.controls.play(queueIdx);
      } else {
        void playback.controls.play(undefined, toPlaybackTrack(tr));
      }
      if (!isDesktop) {
        navigate(`/triage/${styleId}/${blockId}/buckets/${bucketId}/player`);
      }
    },
    [isStagingBucket, playback.controls, playback.queue.tracks, isDesktop, navigate, styleId, blockId, bucketId],
  );

  if (isLoading) return <FullScreenLoader />;
  if (isError) {
    const code = error instanceof ApiError ? error.code : 'unknown';
    if (code === 'triage_block_not_found' || (error instanceof ApiError && error.status === 404)) {
      return (
        <EmptyState
          title={t('triage.errors.block_not_found_title')}
          body={
            <Anchor component={Link} to={`/triage/${styleId}`}>
              {t('triage.detail.back_to_list')}
            </Anchor>
          }
        />
      );
    }
    return (
      <EmptyState
        title={t('triage.errors.service_unavailable')}
        body={
          <Anchor component={Link} to={`/triage/${styleId}`}>
            {t('triage.detail.back_to_list')}
          </Anchor>
        }
      />
    );
  }
  if (!block) return null;

  const bucket = block.buckets.find((b) => b.id === bucketId);
  if (!bucket) {
    return (
      <EmptyState
        title={t('triage.errors.bucket_not_found_title')}
        body={
          <Anchor component={Link} to={`/triage/${styleId}/${blockId}`}>
            {t('triage.bucket.back_to_block', { name: block.name })}
          </Anchor>
        }
      />
    );
  }

  // Mobile player outlet short-circuit
  if (onPlayerSubpath) {
    if (!isStagingBucket) {
      return (
        <Navigate to={`/triage/${styleId}/${blockId}/buckets/${bucketId}`} replace />
      );
    }
    return (
      <Outlet context={{ items: playerItems } satisfies BucketDetailOutletContext} />
    );
  }

  const showMoveMenu = block.status === 'IN_PROGRESS';
  const showBulkTransfer =
    block.status === 'FINALIZED' &&
    bucket.bucket_type !== 'STAGING' &&
    bucket.track_count > 0;

  const handleOpenBulk = async () => {
    if (collecting) return;
    setCollecting(true);
    try {
      // Drain — `fetchNextPage()` resolves with the latest InfiniteData snapshot,
      // so we re-check via the returned `result.hasNextPage` rather than the
      // closed-over `tracksQuery` (which stays stale until React re-renders).
      let result = await tracksQuery.fetchNextPage();
      while (result.hasNextPage) {
        result = await tracksQuery.fetchNextPage();
      }
      const allIds = (result.data?.pages ?? []).flatMap((p) =>
        p.items.map((tr) => tr.track_id),
      );
      setBulkTrackIds(allIds);
      setBulkTransferOpen(true);
    } catch {
      notifications.show({ color: 'red', message: t('errors.network') });
    } finally {
      setCollecting(false);
    }
  };

  const handleMove = (trackId: string, toBucket: TriageBucket) => {
    const input: MoveInput = {
      fromBucketId: bucket.id,
      toBucketId: toBucket.id,
      trackIds: [trackId],
    };
    const snapshot: MoveSnapshot = takeSnapshot(qc, blockId, bucket.id);
    move.mutate(input, {
      onSuccess: () => {
        const toastId = `triage-move-${Date.now()}-${trackId}`;
        notifications.show({
          id: toastId,
          color: 'green',
          autoClose: 5000,
          message: (
            <Group justify="space-between" gap="md">
              <Text size="sm">
                {t('triage.move.toast.moved', {
                  count: 1,
                  to: bucketLabel(toBucket, t),
                })}
              </Text>
              <Anchor
                component="button"
                onClick={async () => {
                  // Gate: don't undo while original move pending or another undo inflight
                  if (undoInflight.current || move.isPending) return;
                  undoInflight.current = true;
                  notifications.hide(toastId);
                  try {
                    await undoMoveDirect(qc, blockId, styleId, input, snapshot);
                    notifications.show({
                      message: t('triage.move.toast.undone'),
                      color: 'green',
                    });
                  } catch {
                    notifications.show({
                      message: t('triage.move.toast.undo_failed'),
                      color: 'red',
                    });
                  } finally {
                    undoInflight.current = false;
                  }
                }}
              >
                {t('triage.move.toast.undo_action')}
              </Anchor>
            </Group>
          ),
        });
      },
      onError: (err) => {
        const code = err instanceof ApiError ? err.code : 'unknown';
        let messageKey = 'triage.move.toast.error';
        if (code === 'target_bucket_inactive' || code === 'invalid_state') {
          messageKey = 'triage.move.toast.invalid_target';
        } else if (
          code === 'triage_block_not_found' ||
          code === 'bucket_not_found' ||
          code === 'tracks_not_in_source'
        ) {
          messageKey = 'triage.move.toast.stale_state';
        }
        notifications.show({ message: t(messageKey), color: 'red' });
      },
    });
  };

  const tracksList = (
    <BucketTracksList
      blockId={blockId}
      bucket={bucket}
      buckets={block.buckets}
      showMoveMenu={showMoveMenu}
      onMove={handleMove}
      onTransfer={(trackId) => setTransferTrackId(trackId)}
      blockStatus={block.status}
      rawSearch={rawSearch}
      onRawSearchChange={setRawSearch}
      debouncedSearch={debouncedSearch}
      onPlay={isStagingBucket ? playTrack : undefined}
      currentTrackId={isStagingBucket ? (playback.track.current?.id ?? null) : null}
    />
  );

  return (
    <Stack gap="lg">
      <Anchor
        component={Link}
        to={`/triage/${styleId}/${blockId}`}
        c="var(--color-fg)"
        td="none"
      >
        {t('triage.bucket.back_to_block', { name: block.name })}
      </Anchor>
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap" align="center">
          <Title order={2}>{bucketLabel(bucket, t)}</Title>
          {block?.status === 'IN_PROGRESS' &&
            bucket.bucket_type !== 'STAGING' &&
            bucket.track_count > 0 && (
              <Button
                component={Link}
                to={`/curate/${block.style_id}/${block.id}/${bucket.id}`}
                variant="default"
              >
                {t('curate.triage_cta.from_bucket')}
              </Button>
            )}
          {showBulkTransfer && (
            <Button
              variant="light"
              leftSection={<IconArrowsExchange size={14} />}
              onClick={handleOpenBulk}
              loading={collecting}
              disabled={collecting}
            >
              {t('triage.transfer.bulk.cta')}
            </Button>
          )}
        </Group>
        <Text c="dimmed" size="sm">
          {t('triage.bucket.header.subtitle', {
            count: bucket.track_count,
            block_name: block.name,
            from: block.date_from,
            to: block.date_to,
          })}
        </Text>
      </Stack>
      {isDesktop && isStagingBucket ? (
        <Flex gap="lg" align="flex-start" wrap="nowrap">
          <BucketPlayerPanel blockId={blockId} bucketId={bucketId} items={playerItems} />
          <div style={{ flex: 1, minWidth: 0 }}>{tracksList}</div>
        </Flex>
      ) : (
        tracksList
      )}
      {transferTrackId && (
        <TransferModal
          opened
          onClose={() => setTransferTrackId(null)}
          srcBlock={block}
          trackIds={[transferTrackId]}
          styleId={styleId}
        />
      )}
      {bulkTransferOpen && bulkTrackIds && (
        <TransferModal
          opened
          onClose={() => {
            setBulkTransferOpen(false);
            setBulkTrackIds(null);
          }}
          srcBlock={block}
          trackIds={bulkTrackIds}
          styleId={styleId}
          mode="bulk"
        />
      )}
    </Stack>
  );
}
