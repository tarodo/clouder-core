import { Card, Group, Stack, Text } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { BucketBadge } from './BucketBadge';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';

export interface BucketCardProps {
  bucket: TriageBucket;
  styleId: string;
  blockId: string;
}

export function BucketCard({ bucket, styleId, blockId }: BucketCardProps) {
  const { t } = useTranslation();
  const dimmed = bucket.bucket_type === 'STAGING' && bucket.inactive;
  return (
    <Card
      component={Link}
      to={`/triage/${styleId}/${blockId}/buckets/${bucket.id}`}
      withBorder
      padding="md"
      style={{ opacity: dimmed ? 0.5 : 1, textDecoration: 'none', color: 'inherit' }}
      aria-label={t('triage.move.menu.destination_aria', { label: bucketLabel(bucket, t) })}
    >
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap">
          <BucketBadge bucket={bucket} />
          <Text size="lg" fw={600} className="font-mono">
            {bucket.track_count}
          </Text>
        </Group>
      </Stack>
    </Card>
  );
}
