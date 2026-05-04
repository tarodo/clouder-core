import { useEffect, useMemo, useState } from 'react';
import { Button, Center, Select, Stack, Text, Title } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useStyles } from '../../../hooks/useStyles';
import { useTriageBlocksByStyle } from '../../triage/hooks/useTriageBlocksByStyle';
import { useTriageBlock } from '../../triage/hooks/useTriageBlock';
import { EmptyState } from '../../../components/EmptyState';
import { CurateSkeleton } from './CurateSkeleton';
import { nextSuggestedBucket } from '../lib/nextSuggestedBucket';

export interface CurateSetupPageProps {
  styleId: string;
}

export function CurateSetupPage({ styleId }: CurateSetupPageProps) {
  const { t } = useTranslation();
  const styles = useStyles();
  const blocks = useTriageBlocksByStyle(styleId, 'IN_PROGRESS');
  const styleName = styles.data?.items?.find((s) => s.id === styleId)?.name ?? styleId;

  const allBlocks = useMemo(
    () => blocks.data?.pages?.flatMap((p) => p.items) ?? [],
    [blocks.data],
  );

  const blockItems = useMemo(
    () =>
      allBlocks.map((b) => ({
        value: b.id,
        label: `${b.name} (${b.date_from} → ${b.date_to})`,
      })),
    [allBlocks],
  );

  const [blockId, setBlockId] = useState<string | null>(null);
  useEffect(() => {
    if (!blockId && blockItems.length > 0) setBlockId(blockItems[0]?.value ?? null);
  }, [blockId, blockItems]);

  const blockDetail = useTriageBlock(blockId ?? '');
  const eligibleBuckets = useMemo(
    () =>
      (blockDetail.data?.buckets ?? []).filter(
        (b) => b.bucket_type !== 'STAGING' && b.track_count > 0,
      ),
    [blockDetail.data],
  );
  const bucketItems = useMemo(
    () =>
      eligibleBuckets.map((b) => ({
        value: b.id,
        label: `${b.bucket_type} (${b.track_count})`,
      })),
    [eligibleBuckets],
  );

  const [bucketId, setBucketId] = useState<string | null>(null);
  useEffect(() => {
    if (!blockDetail.data) return;
    const suggested = nextSuggestedBucket(blockDetail.data.buckets, '');
    if (suggested) setBucketId(suggested.id);
    else if (eligibleBuckets[0]) setBucketId(eligibleBuckets[0].id);
    else setBucketId(null);
  }, [blockDetail.data, eligibleBuckets]);

  if (blocks.isLoading) return <CurateSkeleton />;

  if (allBlocks.length === 0) {
    return (
      <Center p="xl">
        <EmptyState
          title={t('curate.setup.no_active_blocks_title', { style_name: styleName })}
          body={
            <Stack align="center" gap="md">
              <Text>{t('curate.setup.no_active_blocks_body')}</Text>
              <Button component={Link} to={`/triage/${styleId}`}>
                {t('curate.setup.open_triage_cta')}
              </Button>
            </Stack>
          }
        />
      </Center>
    );
  }

  const submitTo = blockId && bucketId ? `/curate/${styleId}/${blockId}/${bucketId}` : '';
  const canSubmit = !!submitTo;

  return (
    <Center p="xl">
      <Stack gap="md" style={{ width: 480, maxWidth: '100%' }}>
        <Title order={2}>{t('curate.setup.title')}</Title>

        <Select
          label={t('curate.setup.block_select_label')}
          placeholder={t('curate.setup.block_select_placeholder')}
          data={blockItems}
          value={blockId}
          onChange={setBlockId}
          allowDeselect={false}
        />

        {blockId && bucketItems.length === 0 && !blockDetail.isLoading && (
          <EmptyState
            title={t('curate.setup.no_eligible_buckets_title')}
            body={t('curate.setup.no_eligible_buckets_body')}
          />
        )}

        {bucketItems.length > 0 && (
          <Select
            label={t('curate.setup.bucket_select_label')}
            placeholder={t('curate.setup.bucket_select_placeholder')}
            data={bucketItems}
            value={bucketId}
            onChange={setBucketId}
            allowDeselect={false}
          />
        )}

        <Button component={Link} to={submitTo} disabled={!canSubmit}>
          {t('curate.setup.start_cta')}
        </Button>
      </Stack>
    </Center>
  );
}
