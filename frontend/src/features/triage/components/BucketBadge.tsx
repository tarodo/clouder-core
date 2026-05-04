import { Badge } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';

export interface BucketBadgeProps {
  bucket: TriageBucket;
  size?: 'xs' | 'sm' | 'md' | 'lg';
}

/**
 * All bucket types render with the same `outline` variant + size for visual
 * cohesion. Differentiation is via typography: technical bucket codes (NEW,
 * OLD, NOT, UNCLASSIFIED, DISCARD) use the mono family (matches the design
 * spec's BPM/key/error-code badge convention); staging category names use the
 * sans family. Inactive staging buckets are dimmed to gray.
 */
export function BucketBadge({ bucket, size = 'sm' }: BucketBadgeProps) {
  const { t } = useTranslation();
  const isStaging = bucket.bucket_type === 'STAGING';
  const color = bucket.inactive ? 'gray' : undefined;
  return (
    <Badge
      size={size}
      variant="outline"
      color={color}
      ff={isStaging ? 'sans' : 'mono'}
    >
      {bucketLabel(bucket, t)}
    </Badge>
  );
}
