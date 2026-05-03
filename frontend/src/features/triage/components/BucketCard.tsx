import { Card, Group, Stack, Text, UnstyledButton } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { BucketBadge } from './BucketBadge';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';

export type BucketCardMode = 'navigate' | 'select';

export interface BucketCardProps {
  bucket: TriageBucket;
  styleId: string;
  blockId: string;
  mode?: BucketCardMode;
  onSelect?: (bucket: TriageBucket) => void;
  disabled?: boolean;
}

export function BucketCard({
  bucket,
  styleId,
  blockId,
  mode = 'navigate',
  onSelect,
  disabled,
}: BucketCardProps) {
  const { t } = useTranslation();
  const dimmed = bucket.bucket_type === 'STAGING' && bucket.inactive;
  const ariaLabel = t('triage.move.menu.destination_aria', { label: bucketLabel(bucket, t) });

  const inner = (
    <Stack gap="xs">
      <Group justify="space-between" wrap="nowrap">
        <BucketBadge bucket={bucket} />
        <Text size="lg" fw={600} className="font-mono">
          {bucket.track_count}
        </Text>
      </Group>
    </Stack>
  );

  if (mode === 'select') {
    const isDisabled = disabled || dimmed;
    return (
      <UnstyledButton
        onClick={() => onSelect?.(bucket)}
        disabled={isDisabled}
        aria-label={ariaLabel}
        style={{ width: '100%', opacity: dimmed ? 0.5 : 1 }}
      >
        <Card withBorder padding="md">
          {inner}
        </Card>
      </UnstyledButton>
    );
  }

  return (
    <Card
      component={Link}
      to={`/triage/${styleId}/${blockId}/buckets/${bucket.id}`}
      withBorder
      padding="md"
      style={{ opacity: dimmed ? 0.5 : 1, textDecoration: 'none', color: 'inherit' }}
      aria-label={ariaLabel}
    >
      {inner}
    </Card>
  );
}
