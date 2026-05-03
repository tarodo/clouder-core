import { Badge } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';

export interface BucketBadgeProps {
  bucket: TriageBucket;
  size?: 'xs' | 'sm' | 'md' | 'lg';
}

export function BucketBadge({ bucket, size = 'sm' }: BucketBadgeProps) {
  const { t } = useTranslation();
  const variant = bucket.bucket_type === 'STAGING' ? 'outline' : 'light';
  const color = bucket.inactive ? 'gray' : undefined;
  return (
    <Badge size={size} variant={variant} color={color}>
      {bucketLabel(bucket, t)}
    </Badge>
  );
}
