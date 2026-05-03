import { useState } from 'react';
import {
  Button,
  Group,
  Loader,
  Modal,
  Stack,
  Text,
} from '@mantine/core';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { ApiError } from '../../../api/error';
import { api } from '../../../api/client';
import {
  type TriageBlock,
  triageBlockKey,
} from '../hooks/useTriageBlock';
import {
  triageBlocksByStyleKey,
  type TriageStatus,
} from '../hooks/useTriageBlocksByStyle';
import {
  useFinalizeTriageBlock,
  type FinalizeErrorBody,
  type InactiveBucketRow,
} from '../hooks/useFinalizeTriageBlock';
import { schedulePendingFinalizeRecovery } from '../lib/pendingFinalizeRecovery';
import { FinalizeSummaryRow } from './FinalizeSummaryRow';
import { FinalizeBlockerRow } from './FinalizeBlockerRow';

const STATUSES: (TriageStatus | undefined)[] = ['IN_PROGRESS', 'FINALIZED', undefined];

export interface FinalizeModalProps {
  opened: boolean;
  onClose: () => void;
  block: TriageBlock;
  styleId: string;
}

type Phase = 'idle' | 'pending' | 'recovering';

export function FinalizeModal({ opened, onClose, block, styleId }: FinalizeModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const finalize = useFinalizeTriageBlock(block.id, styleId);

  const [phase, setPhase] = useState<Phase>('idle');
  const [serverInactive, setServerInactive] = useState<InactiveBucketRow[] | null>(null);

  const localInactive: InactiveBucketRow[] = block.buckets
    .filter((b) => b.bucket_type === 'STAGING' && b.inactive && b.track_count > 0)
    .map((b) => ({
      id: b.id,
      category_id: b.category_id ?? '',
      track_count: b.track_count,
    }));
  const inactiveBuckets = serverInactive ?? localInactive;
  const blocked = inactiveBuckets.length > 0;

  const stagingActive = block.buckets.filter(
    (b) => b.bucket_type === 'STAGING' && !b.inactive,
  );
  const totalToPromote = stagingActive.reduce((acc, b) => acc + b.track_count, 0);

  const closeIfIdle = () => {
    if (phase === 'pending' || phase === 'recovering') return;
    setPhase('idle');
    setServerInactive(null);
    onClose();
  };

  const scheduleRecovery = () => {
    setPhase('recovering');
    schedulePendingFinalizeRecovery({
      blockId: block.id,
      refetch: () =>
        qc.fetchQuery({
          queryKey: triageBlockKey(block.id),
          queryFn: () => api<TriageBlock>(`/triage/blocks/${block.id}`),
        }),
      onSuccess: () => {
        const refreshed = qc.getQueryData<TriageBlock>(triageBlockKey(block.id));
        const stagingPromoted = (refreshed?.buckets ?? []).filter(
          (b) => b.bucket_type === 'STAGING' && !b.inactive,
        );
        const promotedCount = stagingPromoted.reduce((a, c) => a + c.track_count, 0);
        const promotedM = stagingPromoted.length;
        notifications.show({
          color: 'green',
          message: t('triage.finalize.toast.success_recovered', {
            count: promotedCount,
            blockName: block.name,
            categoryCount: promotedM,
          }),
        });
        qc.invalidateQueries({ queryKey: triageBlockKey(block.id) });
        for (const s of STATUSES) {
          qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
        }
        setPhase('idle');
        onClose();
      },
      onFailure: () => {
        notifications.show({
          color: 'red',
          message: t('triage.finalize.toast.cold_start_terminal'),
        });
        setPhase('idle');
      },
    });
  };

  const handleSubmit = () => {
    setPhase('pending');
    finalize.mutate(undefined, {
      onSuccess: (resp) => {
        const promoted = resp.promoted ?? {};
        const n = Object.values(promoted).reduce((a, c) => a + c, 0);
        const m = Object.keys(promoted).length;
        notifications.show({
          color: 'green',
          message: t('triage.finalize.toast.success', {
            count: n,
            blockName: block.name,
            categoryCount: m,
          }),
        });
        setPhase('idle');
        onClose();
      },
      onError: (err) => {
        handleFinalizeError({
          err,
          t,
          qc,
          blockId: block.id,
          styleId,
          setServerInactive,
          setPhase,
          scheduleRecovery,
          close: onClose,
        });
      },
    });
  };

  const title = blocked
    ? t('triage.finalize.blocker.title')
    : t('triage.finalize.confirm.title', { blockName: block.name });

  return (
    <Modal opened={opened} onClose={closeIfIdle} size="lg" title={title}>
      {blocked ? (
        <BlockerVariant
          inactiveBuckets={inactiveBuckets}
          block={block}
          styleId={styleId}
          onClose={closeIfIdle}
        />
      ) : (
        <ConfirmVariant
          stagingActive={stagingActive}
          totalToPromote={totalToPromote}
          phase={phase}
          onSubmit={handleSubmit}
          onCancel={closeIfIdle}
        />
      )}
    </Modal>
  );
}

interface ConfirmVariantProps {
  stagingActive: TriageBlock['buckets'];
  totalToPromote: number;
  phase: Phase;
  onSubmit: () => void;
  onCancel: () => void;
}

function ConfirmVariant({
  stagingActive,
  totalToPromote,
  phase,
  onSubmit,
  onCancel,
}: ConfirmVariantProps) {
  const { t } = useTranslation();
  const isEmpty = stagingActive.length === 0;
  return (
    <Stack gap="md">
      <Text>
        {isEmpty
          ? t('triage.finalize.confirm.empty_summary')
          : t('triage.finalize.confirm.body', {
              count: totalToPromote,
              categoryCount: stagingActive.length,
            })}
      </Text>
      {!isEmpty && (
        <Stack gap="xs">
          {stagingActive.map((b) => (
            <FinalizeSummaryRow key={b.id} bucket={b} />
          ))}
        </Stack>
      )}
      {phase === 'recovering' && (
        <Group gap="xs">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            {t('triage.finalize.confirm.recovering')}
          </Text>
        </Group>
      )}
      <Group justify="flex-end" gap="sm">
        <Button variant="subtle" onClick={onCancel} disabled={phase !== 'idle'}>
          {t('triage.finalize.confirm.cancel')}
        </Button>
        <Button onClick={onSubmit} loading={phase === 'pending'} disabled={phase !== 'idle'}>
          {t('triage.finalize.confirm.submit')}
        </Button>
      </Group>
    </Stack>
  );
}

interface BlockerVariantProps {
  inactiveBuckets: InactiveBucketRow[];
  block: TriageBlock;
  styleId: string;
  onClose: () => void;
}

function BlockerVariant({
  inactiveBuckets,
  block,
  styleId,
  onClose,
}: BlockerVariantProps) {
  const { t } = useTranslation();
  return (
    <Stack gap="md">
      <Text>{t('triage.finalize.blocker.body', { count: inactiveBuckets.length })}</Text>
      <Stack gap="xs">
        {inactiveBuckets.map((ib) => {
          const localBucket = block.buckets.find((b) => b.id === ib.id);
          const name =
            localBucket?.category_name ?? t('triage.finalize.blocker.unknown_category');
          return (
            <FinalizeBlockerRow
              key={ib.id}
              categoryName={name}
              trackCount={ib.track_count}
              href={`/triage/${styleId}/${block.id}/buckets/${ib.id}`}
              onNavigate={onClose}
            />
          );
        })}
      </Stack>
      <Group justify="flex-end" gap="sm">
        <Button variant="subtle" onClick={onClose}>
          {t('triage.finalize.blocker.dismiss')}
        </Button>
        <Button disabled>{t('triage.finalize.confirm.submit')}</Button>
      </Group>
    </Stack>
  );
}

interface ErrorCtx {
  err: ApiError | unknown;
  t: TFunction;
  qc: QueryClient;
  blockId: string;
  styleId: string;
  setServerInactive: (rows: InactiveBucketRow[] | null) => void;
  setPhase: (p: Phase) => void;
  scheduleRecovery: () => void;
  close: () => void;
}

function handleFinalizeError(ctx: ErrorCtx): void {
  const { err, t, qc, blockId, styleId } = ctx;
  if (!(err instanceof ApiError)) {
    notifications.show({ color: 'red', message: t('errors.network') });
    ctx.setPhase('idle');
    return;
  }
  if (err.status === 503) {
    ctx.scheduleRecovery();
    return;
  }
  if (err.code === 'inactive_buckets_have_tracks') {
    const body = err.raw as FinalizeErrorBody | undefined;
    const rows = body?.inactive_buckets ?? [];
    ctx.setServerInactive(rows);
    qc.invalidateQueries({ queryKey: triageBlockKey(blockId) });
    notifications.show({
      color: 'orange',
      message: t('triage.finalize.toast.blocked_race', { count: rows.length }),
    });
    ctx.setPhase('idle');
    return;
  }
  if (err.code === 'triage_block_not_found') {
    notifications.show({ color: 'red', message: t('triage.finalize.toast.stale_block') });
    qc.invalidateQueries({ queryKey: triageBlockKey(blockId) });
    for (const s of STATUSES) qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
    ctx.setPhase('idle');
    ctx.close();
    return;
  }
  if (err.code === 'invalid_state') {
    notifications.show({ color: 'red', message: t('triage.finalize.toast.already_finalized') });
    qc.invalidateQueries({ queryKey: triageBlockKey(blockId) });
    ctx.setPhase('idle');
    ctx.close();
    return;
  }
  notifications.show({ color: 'red', message: t('triage.finalize.toast.error') });
  ctx.setPhase('idle');
}
