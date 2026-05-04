import type { TriageBucket } from '../../triage/lib/bucketLabels';

const PRIORITY: ReadonlyArray<TriageBucket['bucket_type']> = ['NEW', 'UNCLASSIFIED', 'OLD', 'NOT'];

export function nextSuggestedBucket(
  buckets: TriageBucket[],
  currentBucketId: string,
): TriageBucket | null {
  const currentBucket = buckets.find((b) => b.id === currentBucketId);
  const currentTypeIndex = currentBucket ? PRIORITY.indexOf(currentBucket.bucket_type) : -1;

  // Search from the type after the current one, then wrap around
  const orderedTypes =
    currentTypeIndex === -1
      ? PRIORITY
      : [...PRIORITY.slice(currentTypeIndex + 1), ...PRIORITY.slice(0, currentTypeIndex + 1)];

  for (const type of orderedTypes) {
    const candidate = buckets.find(
      (b) => b.bucket_type === type && b.id !== currentBucketId && b.track_count > 0,
    );
    if (candidate) return candidate;
  }
  return null;
}
