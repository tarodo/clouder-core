import { describe, expect, it } from 'vitest';
import { suggestedDestinations } from '../suggestedDestinations';
import type { TriageBucket } from '../bucketLabels';

const stage = (id: string, category_id: string, inactive = false): TriageBucket => ({
  id, bucket_type: 'STAGING', category_id, category_name: id, inactive, track_count: 0,
});

const buckets: TriageBucket[] = [
  { id: 'new', bucket_type: 'NEW', inactive: false, track_count: 3 },
  { id: 'disc', bucket_type: 'DISCARD', inactive: false, track_count: 0 },
  stage('s-a', 'c-a'),
  stage('s-b', 'c-b'),
  stage('s-c', 'c-c'),
  stage('s-old', 'c-old', true),
];

describe('suggestedDestinations', () => {
  it('keep: the first two categories', () => {
    expect(suggestedDestinations({ keep: true, category_ids: ['c-b', 'c-a', 'c-c'] }, buckets))
      .toEqual({ primary: 's-b', secondary: 's-a' });
  });

  it('predicted discard: DISCARD, then the first category', () => {
    expect(suggestedDestinations({ keep: false, category_ids: ['c-c', 'c-a'] }, buckets))
      .toEqual({ primary: 'disc', secondary: 's-c' });
  });

  it('no keep head: the first two categories', () => {
    expect(suggestedDestinations({ keep: null, category_ids: ['c-a', 'c-c'] }, buckets))
      .toEqual({ primary: 's-a', secondary: 's-c' });
  });

  it('skips a deleted or inactive category, so the next one moves up', () => {
    expect(
      suggestedDestinations({ keep: true, category_ids: ['c-gone', 'c-old', 'c-c', 'c-b'] }, buckets),
    ).toEqual({ primary: 's-c', secondary: 's-b' });
  });

  it('no prediction: nothing lights', () => {
    expect(suggestedDestinations(null, buckets)).toEqual({ primary: null, secondary: null });
    expect(suggestedDestinations(undefined, buckets)).toEqual({ primary: null, secondary: null });
  });

  it('only one category alive: no secondary', () => {
    expect(suggestedDestinations({ keep: true, category_ids: ['c-gone', 'c-a'] }, buckets))
      .toEqual({ primary: 's-a', secondary: null });
  });
});
