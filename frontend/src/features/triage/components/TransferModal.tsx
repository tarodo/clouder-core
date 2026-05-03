import { useEffect, useRef, useState } from 'react';
import {
  Anchor,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  Stack,
  Text,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { ApiError } from '../../../api/error';
import { EmptyState } from '../../../components/EmptyState';
import { useTriageBlock, triageBlockKey, type TriageBlock } from '../hooks/useTriageBlock';
import {
  useTriageBlocksByStyle,
  triageBlocksByStyleKey,
  type TriageBlockSummary,
  type TriageStatus,
} from '../hooks/useTriageBlocksByStyle';
import { useTransferTracks } from '../hooks/useTransferTracks';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';
import { BucketGrid } from './BucketGrid';
import { TransferBlockOption } from './TransferBlockOption';

const STATUSES: (TriageStatus | undefined)[] = ['IN_PROGRESS', 'FINALIZED', undefined];
const BULK_CHUNK_SIZE = 1000;

export interface TransferModalProps {
  opened: boolean;
  onClose: () => void;
  srcBlock: TriageBlock;
  trackIds: string[];
  styleId: string;
  mode?: 'single' | 'bulk';
}

export function TransferModal({
  opened,
  onClose,
  srcBlock,
  trackIds,
  styleId,
  mode = 'single',
}: TransferModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [step, setStep] = useState<'block' | 'bucket'>('block');
  const [targetBlockId, setTargetBlockId] = useState<string | null>(null);
  const [bulkPhase, setBulkPhase] = useState<{ k: number; m: number } | null>(null);
  const cancelledRef = useRef(false);

  const siblingsQuery = useTriageBlocksByStyle(styleId, 'IN_PROGRESS');
  const targetBlockQuery = useTriageBlock(targetBlockId ?? '');
  const transfer = useTransferTracks(srcBlock.id);

  useEffect(() => {
    if (!opened) {
      setStep('block');
      setTargetBlockId(null);
      setBulkPhase(null);
    } else {
      cancelledRef.current = false;
    }
  }, [opened]);

  const siblings: TriageBlockSummary[] = (siblingsQuery.data?.pages ?? [])
    .flatMap((p) => p.items)
    .filter((b) => b.id !== srcBlock.id);

  const handleClose = () => {
    cancelledRef.current = true;
    setBulkPhase(null);
    setStep('block');
    setTargetBlockId(null);
    onClose();
  };

  const handlePickBlock = (id: string) => {
    setTargetBlockId(id);
    setStep('bucket');
  };

  const invalidateForBulkError = (code: string) => {
    if (code === 'triage_block_not_found' || code === 'tracks_not_in_source') {
      qc.invalidateQueries({ queryKey: ['triage', 'bucketTracks', srcBlock.id] });
    } else if (code === 'target_bucket_not_found' || code === 'invalid_state') {
      for (const s of STATUSES) {
        qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
      }
    } else if (code === 'target_bucket_inactive' && targetBlockId) {
      qc.invalidateQueries({ queryKey: triageBlockKey(targetBlockId) });
    }
  };

  const runBulkTransfer = async (resolvedBlockId: string, bucket: TriageBucket) => {
    cancelledRef.current = false;
    const total = trackIds.length;
    const chunks: string[][] = [];
    for (let i = 0; i < total; i += BULK_CHUNK_SIZE) {
      chunks.push(trackIds.slice(i, i + BULK_CHUNK_SIZE));
    }
    let transferred = 0;
    for (let i = 0; i < chunks.length; i++) {
      if (cancelledRef.current) return;
      setBulkPhase({ k: i + 1, m: chunks.length });
      try {
        const resp = await transfer.mutateAsync({
          targetBlockId: resolvedBlockId,
          targetBucketId: bucket.id,
          trackIds: chunks[i]!,
          styleId,
        });
        transferred += resp.transferred;
      } catch (err) {
        const code = err instanceof ApiError ? err.code : 'unknown';
        invalidateForBulkError(code);
        notifications.show({
          color: 'orange',
          message: t('triage.transfer.bulk.toast.partial', {
            count: transferred,
            total,
            blockName: targetBlockQuery.data?.name ?? '',
            bucketLabel: bucketLabel(bucket, t),
          }),
        });
        setBulkPhase(null);
        return;
      }
    }
    setBulkPhase(null);
    notifications.show({
      color: 'green',
      message: t('triage.transfer.bulk.toast.success', {
        count: transferred,
        blockName: targetBlockQuery.data?.name ?? '',
        bucketLabel: bucketLabel(bucket, t),
      }),
    });
    handleClose();
  };

  const handlePickBucket = (bucket: TriageBucket) => {
    if (!targetBlockId) return;
    if (mode === 'single') {
      transfer.mutate(
        { targetBlockId, targetBucketId: bucket.id, trackIds, styleId },
        {
          onSuccess: () => {
            notifications.show({
              color: 'green',
              message: t('triage.transfer.toast.transferred', {
                count: trackIds.length,
                block_name: targetBlockQuery.data?.name ?? '',
                bucket_label: bucketLabel(bucket, t),
              }),
            });
            handleClose();
          },
          onError: (err) =>
            handleTransferError({
              err,
              t,
              qc,
              styleId,
              srcBlockId: srcBlock.id,
              targetBlockId,
              setStep,
              close: handleClose,
            }),
        },
      );
      return;
    }
    void runBulkTransfer(targetBlockId, bucket);
  };

  const title =
    step === 'block'
      ? t('triage.transfer.modal.title_pick_block')
      : t('triage.transfer.modal.title_pick_bucket', {
          block_name: targetBlockQuery.data?.name ?? '',
        });

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      size="lg"
      title={title}
    >
      {step === 'block' && (
        <Step1
          loading={siblingsQuery.isLoading}
          siblings={siblings}
          hasNextPage={siblingsQuery.hasNextPage ?? false}
          fetchingNext={siblingsQuery.isFetchingNextPage}
          onPick={handlePickBlock}
          onLoadMore={() => siblingsQuery.fetchNextPage()}
          styleId={styleId}
          onClose={handleClose}
        />
      )}
      {step === 'bucket' && (
        <Step2
          loading={targetBlockQuery.isLoading}
          targetBlock={targetBlockQuery.data}
          transferPending={transfer.isPending}
          bulkPhase={bulkPhase}
          onBack={() => setStep('block')}
          onPick={handlePickBucket}
        />
      )}
    </Modal>
  );
}

interface Step1Props {
  loading: boolean;
  siblings: TriageBlockSummary[];
  hasNextPage: boolean;
  fetchingNext: boolean;
  onPick: (id: string) => void;
  onLoadMore: () => void;
  styleId: string;
  onClose: () => void;
}

function Step1({
  loading,
  siblings,
  hasNextPage,
  fetchingNext,
  onPick,
  onLoadMore,
  styleId,
  onClose,
}: Step1Props) {
  const { t } = useTranslation();
  if (loading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  if (siblings.length === 0) {
    return (
      <EmptyState
        title={t('triage.transfer.empty.no_siblings_title')}
        body={
          <Stack gap="sm">
            <span>{t('triage.transfer.empty.no_siblings_body')}</span>
            <Anchor component={Link} to={`/triage/${styleId}`} onClick={onClose}>
              {t('triage.transfer.empty.no_siblings_cta')}
            </Anchor>
          </Stack>
        }
      />
    );
  }
  return (
    <Stack gap="sm">
      {siblings.map((b) => (
        <TransferBlockOption key={b.id} block={b} onSelect={() => onPick(b.id)} />
      ))}
      {hasNextPage && (
        <Button variant="subtle" loading={fetchingNext} onClick={onLoadMore}>
          {t('triage.transfer.modal.load_more')}
        </Button>
      )}
    </Stack>
  );
}

interface Step2Props {
  loading: boolean;
  targetBlock: TriageBlock | undefined;
  transferPending: boolean;
  bulkPhase: { k: number; m: number } | null;
  onBack: () => void;
  onPick: (bucket: TriageBucket) => void;
}

function Step2({
  loading,
  targetBlock,
  transferPending,
  bulkPhase,
  onBack,
  onPick,
}: Step2Props) {
  const { t } = useTranslation();
  return (
    <Stack gap="md">
      <Group gap="xs">
        <Anchor component="button" type="button" onClick={onBack}>
          {t('triage.transfer.modal.back')}
        </Anchor>
      </Group>
      {loading && (
        <Center py="xl">
          <Loader />
        </Center>
      )}
      {bulkPhase && (
        <Group gap="xs">
          <Loader size="sm" />
          <Text size="sm">
            {t('triage.transfer.bulk.modal.batch_progress', {
              k: bulkPhase.k,
              m: bulkPhase.m,
            })}
          </Text>
        </Group>
      )}
      {targetBlock && (
        <BucketGrid
          buckets={targetBlock.buckets}
          styleId={targetBlock.style_id}
          blockId={targetBlock.id}
          mode="select"
          cols={{ base: 1, xs: 2 }}
          onSelect={onPick}
          disabled={transferPending || bulkPhase !== null}
        />
      )}
    </Stack>
  );
}

interface ErrorCtx {
  err: ApiError | unknown;
  t: TFunction;
  qc: QueryClient;
  styleId: string;
  srcBlockId: string;
  targetBlockId: string | null;
  setStep: (s: 'block' | 'bucket') => void;
  close: () => void;
}

function handleTransferError(ctx: ErrorCtx): void {
  const code = ctx.err instanceof ApiError ? ctx.err.code : 'unknown';
  let toastKey: string;
  let next: 'close' | 'step1' | 'stay';

  switch (code) {
    case 'triage_block_not_found':
    case 'tracks_not_in_source':
      toastKey = 'triage.transfer.toast.stale_source';
      ctx.qc.invalidateQueries({ queryKey: ['triage', 'bucketTracks', ctx.srcBlockId] });
      next = 'close';
      break;
    case 'target_bucket_not_found':
      toastKey = 'triage.transfer.toast.stale_target';
      for (const s of STATUSES) ctx.qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(ctx.styleId, s) });
      next = 'step1';
      break;
    case 'invalid_state':
      toastKey = 'triage.transfer.toast.target_finalized';
      for (const s of STATUSES) ctx.qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(ctx.styleId, s) });
      next = 'close';
      break;
    case 'target_bucket_inactive':
      toastKey = 'triage.transfer.toast.target_inactive';
      if (ctx.targetBlockId) ctx.qc.invalidateQueries({ queryKey: triageBlockKey(ctx.targetBlockId) });
      next = 'stay';
      break;
    case 'target_block_style_mismatch':
      toastKey = 'triage.transfer.toast.style_mismatch';
      next = 'close';
      break;
    default:
      toastKey = 'errors.network';
      next = 'stay';
  }

  notifications.show({ color: 'red', message: ctx.t(toastKey) });
  if (next === 'close') ctx.close();
  else if (next === 'step1') ctx.setStep('block');
}
