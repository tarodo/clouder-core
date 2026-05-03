import { describe, it, expect } from 'vitest';
import {
  bucketLabel,
  isTechnical,
  moveDestinationsFor,
  type TriageBucket,
} from '../bucketLabels';

const t = ((key: string, vars?: Record<string, string>) => {
  if (key === 'triage.bucket_type.STAGING_label') return `${vars?.name} (staging)`;
  if (key === 'triage.bucket_type.STAGING_inactive_label')
    return `${vars?.name} (staging, inactive)`;
  return key;
}) as Parameters<typeof bucketLabel>[1];

const tech: TriageBucket = {
  id: 'b1',
  bucket_type: 'NEW',
  category_id: null,
  category_name: null,
  inactive: false,
  track_count: 5,
};

const staging: TriageBucket = {
  id: 'b2',
  bucket_type: 'STAGING',
  category_id: 'c1',
  category_name: 'Tech House',
  inactive: false,
  track_count: 3,
};

const stagingInactive: TriageBucket = {
  ...staging,
  id: 'b3',
  category_name: 'Old Genre',
  inactive: true,
};

describe('bucketLabel', () => {
  it('returns the bucket_type literal for technical buckets', () => {
    expect(bucketLabel(tech, t)).toBe('NEW');
  });
  it('returns "<name> (staging)" for active STAGING', () => {
    expect(bucketLabel(staging, t)).toBe('Tech House (staging)');
  });
  it('returns "<name> (staging, inactive)" for inactive STAGING', () => {
    expect(bucketLabel(stagingInactive, t)).toBe('Old Genre (staging, inactive)');
  });
});

describe('isTechnical', () => {
  it('true for NEW/OLD/NOT/DISCARD/UNCLASSIFIED', () => {
    for (const tp of ['NEW', 'OLD', 'NOT', 'DISCARD', 'UNCLASSIFIED'] as const) {
      expect(isTechnical({ bucket_type: tp })).toBe(true);
    }
  });
  it('false for STAGING', () => {
    expect(isTechnical({ bucket_type: 'STAGING' })).toBe(false);
  });
});

describe('moveDestinationsFor', () => {
  it('excludes the current bucket', () => {
    const result = moveDestinationsFor([tech, staging, stagingInactive], 'b1');
    expect(result.map((b) => b.id)).toEqual(['b2']);
  });
  it('excludes inactive STAGING', () => {
    const result = moveDestinationsFor([tech, staging, stagingInactive], 'b2');
    expect(result.map((b) => b.id)).toEqual(['b1']);
  });
  it('preserves API order', () => {
    const result = moveDestinationsFor([staging, tech, stagingInactive], 'b3');
    expect(result.map((b) => b.id)).toEqual(['b2', 'b1']);
  });
});
