import { useState } from 'react';
import { Anchor, Stack, Text, Title } from '@mantine/core';
import { Link, Navigate, useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { ApiError } from '../../../api/error';
import { EmptyState } from '../../../components/EmptyState';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { useTriageBlock } from '../hooks/useTriageBlock';
import { useDeleteTriageBlock } from '../hooks/useDeleteTriageBlock';
import { TriageBlockHeader } from '../components/TriageBlockHeader';
import { BucketGrid } from '../components/BucketGrid';
import { FinalizeModal } from '../components/FinalizeModal';
import { isTechnical } from '../lib/bucketLabels';

export function TriageDetailPage() {
  const { styleId, id } = useParams<{ styleId: string; id: string }>();
  if (!styleId || !id) return <Navigate to="/triage" replace />;
  return <TriageDetailInner styleId={styleId} blockId={id} />;
}

interface InnerProps {
  styleId: string;
  blockId: string;
}

function TriageDetailInner({ styleId, blockId }: InnerProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data, isLoading, isError, error } = useTriageBlock(blockId);
  const del = useDeleteTriageBlock(styleId);
  const [finalizeOpen, setFinalizeOpen] = useState(false);

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
  if (!data) return null;

  // Buckets arrive ordered NEW, OLD, NOT, UNCLASSIFIED, DISCARD, staging[position ASC]
  // (spec-D §6). Filtering preserves that order within each section.
  const technicalBuckets = data.buckets.filter(isTechnical);
  const stagingBuckets = data.buckets.filter((b) => !isTechnical(b));

  const handleDelete = () => {
    modals.openConfirmModal({
      title: t('triage.delete_modal.title'),
      children: t('triage.delete_modal.body', { name: data.name }),
      labels: {
        confirm: t('triage.delete_modal.confirm'),
        cancel: t('triage.delete_modal.cancel'),
      },
      confirmProps: { color: 'red' },
      onConfirm: () => {
        del.mutate(blockId, {
          onSuccess: () => {
            notifications.show({ message: t('triage.toast.deleted'), color: 'green' });
            navigate(`/triage/${styleId}`);
          },
          onError: (err) => {
            const msg =
              err instanceof ApiError && err.status === 404
                ? t('triage.toast.delete_not_found')
                : t('triage.toast.generic_error');
            notifications.show({ message: msg, color: 'red' });
          },
        });
      },
    });
  };

  return (
    <Stack gap="lg">
      <Anchor component={Link} to={`/triage/${styleId}`} c="var(--color-fg)" td="none">
        {t('triage.detail.back_to_list')}
      </Anchor>
      <TriageBlockHeader
        block={data}
        onDelete={handleDelete}
        onFinalize={() => setFinalizeOpen(true)}
      />
      {technicalBuckets.length > 0 && (
        <Stack gap="sm">
          <Stack gap={2}>
            <Title order={4}>{t('triage.detail.section.technical_title')}</Title>
            <Text size="sm" c="dimmed">
              {t('triage.detail.section.technical_hint')}
            </Text>
          </Stack>
          <BucketGrid buckets={technicalBuckets} styleId={styleId} blockId={blockId} />
        </Stack>
      )}
      {stagingBuckets.length > 0 && (
        <Stack gap="sm">
          <Stack gap={2}>
            <Title order={4}>{t('triage.detail.section.staging_title')}</Title>
            <Text size="sm" c="dimmed">
              {t('triage.detail.section.staging_hint')}
            </Text>
          </Stack>
          <BucketGrid buckets={stagingBuckets} styleId={styleId} blockId={blockId} />
        </Stack>
      )}
      {finalizeOpen && (
        <FinalizeModal
          opened
          onClose={() => setFinalizeOpen(false)}
          block={data}
          styleId={styleId}
        />
      )}
    </Stack>
  );
}
