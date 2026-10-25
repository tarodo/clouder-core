import type { BucketTrack } from '../hooks/useBucketTracks';
import type { TriageBucket } from './bucketLabels';

/** Bucket ids of the lit buttons: primary lit brightly, secondary paler. */
export type Suggested = { primary: string | null; secondary: string | null };

/**
 * Which destination buttons light for a track. `buckets` is the block's full list;
 * renderers light only the buttons they actually render (nothing shifts up).
 */
export function suggestedDestinations(
  prediction: BucketTrack['prediction'],
  buckets: TriageBucket[],
): Suggested {
  if (!prediction) return { primary: null, secondary: null };
  const staging = new Map(
    buckets
      .filter((b) => b.bucket_type === 'STAGING' && !b.inactive && b.category_id)
      .map((b) => [b.category_id, b.id]),
  );
  // Deleted or new categories drop out, so the next one moves up.
  const ranking = prediction.category_ids.flatMap((id) => staging.get(id) ?? []);
  if (prediction.keep === false) {
    const discard = buckets.find((b) => b.bucket_type === 'DISCARD');
    return { primary: discard?.id ?? null, secondary: ranking[0] ?? null };
  }
  return { primary: ranking[0] ?? null, secondary: ranking[1] ?? null };
}

export function suggestionLevel(
  suggested: Suggested | undefined,
  bucketId: string,
): 'primary' | 'secondary' | null {
  if (suggested?.primary === bucketId) return 'primary';
  if (suggested?.secondary === bucketId) return 'secondary';
  return null;
}
