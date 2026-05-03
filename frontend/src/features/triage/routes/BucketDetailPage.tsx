import { useRef, useState } from 'react';
import { Anchor, Button, Group, Stack, Text, Title } from '@mantine/core';
import { Link, Navigate, useParams } from 'react-router';
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
import { useBucketTracks } from '../hooks/useBucketTracks';
import { BucketTracksList } from '../components/BucketTracksList';
import { BucketBadge } from '../components/BucketBadge';
import { TransferModal } from '../components/TransferModal';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';

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
  const tracksQuery = useBucketTracks(blockId, bucketId, '');
  const [bulkTransferOpen, setBulkTransferOpen] = useState(false);
  const [bulkTrackIds, setBulkTrackIds] = useState<string[] | null>(null);
  const [collecting, setCollecting] = useState(false);

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
          <Group gap="md" align="center">
            <Title order={2}>{bucketLabel(bucket, t)}</Title>
            <BucketBadge bucket={bucket} size="md" />
          </Group>
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
      <BucketTracksList
        blockId={blockId}
        bucket={bucket}
        buckets={block.buckets}
        showMoveMenu={showMoveMenu}
        onMove={handleMove}
        onTransfer={(trackId) => setTransferTrackId(trackId)}
        blockStatus={block.status}
      />
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
