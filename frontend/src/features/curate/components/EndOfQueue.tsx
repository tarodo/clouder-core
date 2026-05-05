// frontend/src/features/curate/components/EndOfQueue.tsx
import { useEffect } from 'react';
import { Button, Group, Stack, Text, Title } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { TriageBlock } from '../../triage/hooks/useTriageBlock';
import { bucketLabel } from '../../triage/lib/bucketLabels';
import { nextSuggestedBucket } from '../lib/nextSuggestedBucket';
import { usePlayback } from '../../playback/usePlayback';

export interface EndOfQueueProps {
  styleId: string;
  block: TriageBlock;
  currentBucketId: string;
  totalAssigned: number;
}

export function EndOfQueue({
  styleId,
  block,
  currentBucketId,
  totalAssigned,
}: EndOfQueueProps) {
  const { t } = useTranslation();
  const playback = usePlayback();
  const next = nextSuggestedBucket(block.buckets, currentBucketId);

  useEffect(() => {
    void playback.controls.pause();
  }, [playback.controls]);

  return (
    <Stack gap="lg" align="center" p="xl" data-testid="end-of-queue">
      <Title order={2}>{t('playback.end_of_queue.title')}</Title>
      <Text c="var(--color-fg-muted)">
        {t('playback.end_of_queue.tracks_done', { count: totalAssigned })}
      </Text>
      <Group>
        {next ? (
          // eslint-disable-next-line jsx-a11y/no-autofocus -- intentional: keyboard flow continues with Enter on suggested CTA
          <Button autoFocus component={Link} to={`/curate/${styleId}/${block.id}/${next.id}`}>
            {t('curate.end_of_queue.continue_cta', {
              label: bucketLabel(next, t),
              count: next.track_count,
            })}
          </Button>
        ) : (
          // eslint-disable-next-line jsx-a11y/no-autofocus -- intentional: keyboard flow continues with Enter on Finalize CTA
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
