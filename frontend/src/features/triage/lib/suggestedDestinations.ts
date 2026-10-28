import type { BucketTrack } from '../hooks/useBucketTracks';
import type { TriageBucket } from './bucketLabels';

/** Bucket ids of the lit buttons: primary lit brightly, secondary paler; unsure lights both pale. */
export type Suggested = { primary: string | null; secondary: string | null; unsure?: boolean };

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
  const discard = buckets.find((b) => b.bucket_type === 'DISCARD')?.id ?? null;
  // Near the keep threshold keep-or-discard is a coin flip, while the category still ranks well.
  if (prediction.unsure) return { primary: ranking[0] ?? null, secondary: discard, unsure: true };
  if (prediction.keep === false) return { primary: discard, secondary: ranking[0] ?? null };
  return { primary: ranking[0] ?? null, secondary: ranking[1] ?? null };
}

export function suggestionLevel(
  suggested: Suggested | undefined,
  bucketId: string,
): 'primary' | 'secondary' | null {
  if (suggested?.primary === bucketId) return suggested.unsure ? 'secondary' : 'primary';
  if (suggested?.secondary === bucketId) return 'secondary';
  return null;
}

/** The `suggestion` telemetry prop of a tap on `bucketId`; undefined when nothing was lit. */
export function suggestionTag(
  suggested: Suggested,
  bucketId: string,
): 'first' | 'second' | 'unsure' | 'unlit' | undefined {
  if (!suggested.primary && !suggested.secondary) return undefined;
  if (bucketId !== suggested.primary && bucketId !== suggested.secondary) return 'unlit';
  if (suggested.unsure) return 'unsure';
  return bucketId === suggested.primary ? 'first' : 'second';
}
