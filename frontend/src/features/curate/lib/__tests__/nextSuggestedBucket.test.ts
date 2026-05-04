import { describe, expect, it } from 'vitest';
import type { TriageBucket } from '../../../triage/lib/bucketLabels';
import { nextSuggestedBucket } from '../nextSuggestedBucket';

const tech = (
  id: string,
  t: 'NEW' | 'OLD' | 'NOT' | 'DISCARD' | 'UNCLASSIFIED',
  count: number,
): TriageBucket => ({ id, bucket_type: t, inactive: false, track_count: count });

const stage = (id: string, count: number): TriageBucket => ({
  id,
  bucket_type: 'STAGING',
  inactive: false,
  track_count: count,
  category_id: `c-${id}`,
  category_name: 'X',
});

describe('nextSuggestedBucket', () => {
  it('priority NEW → OLD → NOT → UNCLASSIFIED', () => {
    const buckets = [
      tech('b-new', 'NEW', 5),
      tech('b-uncl', 'UNCLASSIFIED', 3),
      tech('b-old', 'OLD', 7),
      tech('b-not', 'NOT', 9),
    ];
    expect(nextSuggestedBucket(buckets, 'b-current')?.id).toBe('b-new');
    expect(nextSuggestedBucket(buckets, 'b-new')?.id).toBe('b-old');
    expect(nextSuggestedBucket(buckets, 'b-old')?.id).toBe('b-not');
    expect(nextSuggestedBucket(buckets, 'b-not')?.id).toBe('b-uncl');
  });

  it('skips empty buckets', () => {
    const buckets = [tech('b-new', 'NEW', 0), tech('b-old', 'OLD', 5)];
    expect(nextSuggestedBucket(buckets, 'b-x')?.id).toBe('b-old');
  });

  it('skips STAGING and DISCARD', () => {
    const buckets = [stage('s1', 10), tech('b-disc', 'DISCARD', 4), tech('b-new', 'NEW', 1)];
    expect(nextSuggestedBucket(buckets, 'b-x')?.id).toBe('b-new');
  });

  it('skips the current bucket', () => {
    const buckets = [tech('b-new', 'NEW', 0), tech('b-old', 'OLD', 5)];
    expect(nextSuggestedBucket(buckets, 'b-old')).toBeNull();
  });

  it('returns null when no eligible bucket exists', () => {
    expect(nextSuggestedBucket([], 'b-x')).toBeNull();
    expect(
      nextSuggestedBucket([stage('s1', 5), tech('b-disc', 'DISCARD', 2)], 'b-x'),
    ).toBeNull();
  });
});
