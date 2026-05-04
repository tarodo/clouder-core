import type { TriageBucket } from '../../triage/lib/bucketLabels';

const PRIORITY: ReadonlyArray<TriageBucket['bucket_type']> = ['NEW', 'UNCLASSIFIED', 'OLD', 'NOT'];

export function nextSuggestedBucket(
  buckets: TriageBucket[],
  currentBucketId: string,
): TriageBucket | null {
  for (const type of PRIORITY) {
    const candidate = buckets.find(
      (b) => b.bucket_type === type && b.id !== currentBucketId && b.track_count > 0,
    );
    if (candidate) return candidate;
  }
  return null;
}
