import type { TFunction } from 'i18next';

export type TechnicalBucketType = 'NEW' | 'OLD' | 'NOT' | 'DISCARD' | 'UNCLASSIFIED';
export type BucketType = TechnicalBucketType | 'STAGING';

export interface TriageBucket {
  id: string;
  bucket_type: BucketType;
  category_id?: string | null;
  category_name?: string | null;
  inactive: boolean;
  track_count: number;
}

const TECHNICAL_TYPES: ReadonlySet<BucketType> = new Set([
  'NEW',
  'OLD',
  'NOT',
  'DISCARD',
  'UNCLASSIFIED',
]);

export function isTechnical(bucket: Pick<TriageBucket, 'bucket_type'>): boolean {
  return TECHNICAL_TYPES.has(bucket.bucket_type);
}

export function bucketLabel(bucket: TriageBucket, t: TFunction): string {
  if (bucket.bucket_type !== 'STAGING') return bucket.bucket_type;
  const name = bucket.category_name ?? '';
  return bucket.inactive
    ? t('triage.bucket_type.STAGING_inactive_label', { name })
    : t('triage.bucket_type.STAGING_label', { name });
}

export function moveDestinationsFor(
  buckets: TriageBucket[],
  currentBucketId: string,
): TriageBucket[] {
  return buckets.filter((b) => {
    if (b.id === currentBucketId) return false;
    if (b.bucket_type === 'STAGING' && b.inactive) return false;
    return true;
  });
}
