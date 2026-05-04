import { describe, expect, it } from 'vitest';
import type { TriageBucket } from '../../../triage/lib/bucketLabels';
import {
  byDiscard,
  byPosition,
  byTechType,
  resolveStagingHotkeys,
  stagingOverflow,
} from '../destinationMap';

const stage = (id: string, name: string, inactive = false): TriageBucket => ({
  id,
  bucket_type: 'STAGING',
  inactive,
  track_count: 0,
  category_id: `cat-${id}`,
  category_name: name,
});

const tech = (id: string, t: 'NEW' | 'OLD' | 'NOT' | 'DISCARD' | 'UNCLASSIFIED'): TriageBucket => ({
  id,
  bucket_type: t,
  inactive: false,
  track_count: 0,
});

describe('destinationMap.byPosition', () => {
  it('returns the active staging bucket at position 0', () => {
    const buckets = [tech('b-new', 'NEW'), stage('s1', 'Big Room'), stage('s2', 'Hard Techno')];
    expect(byPosition(buckets, 0)?.id).toBe('s1');
    expect(byPosition(buckets, 1)?.id).toBe('s2');
  });

  it('skips inactive staging entries when computing the offset', () => {
    const buckets = [
      stage('s1', 'A', true),
      stage('s2', 'B'),
      stage('s3', 'C', true),
      stage('s4', 'D'),
    ];
    expect(byPosition(buckets, 0)?.id).toBe('s2');
    expect(byPosition(buckets, 1)?.id).toBe('s4');
    expect(byPosition(buckets, 2)).toBeNull();
  });

  it('returns null for out-of-range positions', () => {
    expect(byPosition([stage('s1', 'A')], 5)).toBeNull();
  });

  it('returns null when buckets has zero staging', () => {
    expect(byPosition([tech('b-new', 'NEW')], 0)).toBeNull();
  });
});

describe('destinationMap.byTechType', () => {
  const buckets = [
    tech('b-new', 'NEW'),
    tech('b-old', 'OLD'),
    tech('b-not', 'NOT'),
    tech('b-disc', 'DISCARD'),
  ];
  it('matches NEW / OLD / NOT', () => {
    expect(byTechType(buckets, 'NEW')?.id).toBe('b-new');
    expect(byTechType(buckets, 'OLD')?.id).toBe('b-old');
    expect(byTechType(buckets, 'NOT')?.id).toBe('b-not');
  });
  it('returns null when type missing', () => {
    expect(byTechType([], 'NEW')).toBeNull();
  });
});

describe('destinationMap.byDiscard', () => {
  it('returns the DISCARD bucket', () => {
    expect(byDiscard([tech('b-disc', 'DISCARD')])?.id).toBe('b-disc');
  });
  it('returns null when missing', () => {
    expect(byDiscard([])).toBeNull();
  });
});

describe('destinationMap.resolveStagingHotkeys', () => {
  it('maps the first 9 active staging slots to digits 1-9 in incoming order', () => {
    const buckets = [
      tech('b-new', 'NEW'),
      stage('s1', 'A'),
      stage('s2', 'B', true),
      stage('s3', 'C'),
      stage('s4', 'D'),
    ];
    const slots = resolveStagingHotkeys(buckets);
    expect(slots).toHaveLength(3);
    expect(slots[0]?.id).toBe('s1');
    expect(slots[1]?.id).toBe('s3');
    expect(slots[2]?.id).toBe('s4');
  });

  it('caps slots at 9 — extras are returned via the overflow array', () => {
    const buckets = Array.from({ length: 12 }, (_, i) => stage(`s${i}`, `Cat ${i}`));
    const slots = resolveStagingHotkeys(buckets);
    const overflow = buckets
      .filter((b) => b.bucket_type === 'STAGING' && !b.inactive)
      .slice(9);
    expect(slots).toHaveLength(9);
    expect(overflow.map((b) => b.id)).toEqual(['s9', 's10', 's11']);
  });
});

describe('destinationMap.stagingOverflow', () => {
  it('returns active staging buckets beyond position 9, in order, with inactive filtered out', () => {
    const buckets = [
      stage('s0', 'A'),
      stage('s1', 'B'),
      stage('s2', 'C'),
      stage('s3', 'D'),
      stage('s4', 'E'),
      stage('s5', 'F'),
      stage('s6', 'G'),
      stage('s7', 'H'),
      stage('s8', 'I'),
      stage('s9', 'J'),
      stage('s10', 'K', true), // inactive — skipped from indexing
      stage('s11', 'L'),
      stage('s12', 'M'),
    ];
    const overflow = stagingOverflow(buckets);
    // 12 active staging (s10 inactive); first 9 take positions 0–8, overflow = [s9, s11, s12]
    expect(overflow.map((b) => b.id)).toEqual(['s9', 's11', 's12']);
  });

  it('returns an empty array when fewer than 10 active staging buckets exist', () => {
    expect(stagingOverflow([])).toEqual([]);
    expect(stagingOverflow([stage('s1', 'A'), stage('s2', 'B'), stage('s3', 'C')])).toEqual([]);
    expect(stagingOverflow(Array.from({ length: 9 }, (_, i) => stage(`s${i}`, `Cat ${i}`)))).toEqual([]);
  });
});
