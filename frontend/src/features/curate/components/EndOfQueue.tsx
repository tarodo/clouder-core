// frontend/src/features/curate/components/EndOfQueue.tsx
import { Button, Group, Stack, Text, Title } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { TriageBlock } from '../../triage/hooks/useTriageBlock';
import {
  bucketLabel,
  type TriageBucket,
} from '../../triage/lib/bucketLabels';
import { nextSuggestedBucket } from '../lib/nextSuggestedBucket';

export interface EndOfQueueProps {
  styleId: string;
  block: TriageBlock;
  currentBucketId: string;
  totalAssigned: number;
}

function bodyKey(count: number): string {
  if (count === 0) return 'curate.end_of_queue.body_zero';
  if (count === 1) return 'curate.end_of_queue.body_one';
  return 'curate.end_of_queue.body_other';
}

export function EndOfQueue({
  styleId,
  block,
  currentBucketId,
  totalAssigned,
}: EndOfQueueProps) {
  const { t } = useTranslation();
  const currentBucket: TriageBucket | undefined = block.buckets.find(
    (b) => b.id === currentBucketId,
  );
  const currentLabel = currentBucket ? bucketLabel(currentBucket, t) : '';
  const next = nextSuggestedBucket(block.buckets, currentBucketId);

  return (
    <Stack gap="lg" align="center" p="xl" data-testid="end-of-queue">
      <Title order={2}>{t('curate.end_of_queue.heading', { label: currentLabel })}</Title>
      <Text c="var(--color-fg-muted)">
        {t(bodyKey(totalAssigned), { count: totalAssigned })}
      </Text>
      <Group>
        {next ? (
          <Button autoFocus component={Link} to={`/curate/${styleId}/${block.id}/${next.id}`}>
            {t('curate.end_of_queue.continue_cta', {
              label: bucketLabel(next, t),
              count: next.track_count,
            })}
          </Button>
        ) : (
          <Button autoFocus component={Link} to={`/triage/${styleId}/${block.id}`}>
            {t('curate.end_of_queue.finalize_cta')}
          </Button>
        )}
        <Button variant="default" component={Link} to={`/triage/${styleId}/${block.id}`}>
          {t('curate.end_of_queue.back_to_triage_cta')}
        </Button>
      </Group>
    </Stack>
  );
}
