import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  LAST_CURATE_LOCATION_KEY,
  LAST_CURATE_STYLE_KEY,
  clearLastCurateLocation,
  isStaleLocation,
  readLastCurateLocation,
  readLastCurateStyle,
  writeLastCurateLocation,
  writeLastCurateStyle,
} from '../lastCurateLocation';
import type { TriageBlock } from '../../../triage/hooks/useTriageBlock';

const mkBlock = (overrides: Partial<TriageBlock> = {}): TriageBlock => ({
  id: 'block-1',
  style_id: 'style-1',
  style_name: 'Tech House',
  name: 'TH W17',
  date_from: '2026-04-21',
  date_to: '2026-04-27',
  status: 'IN_PROGRESS',
  created_at: '2026-04-20T00:00:00Z',
  updated_at: '2026-04-20T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'b-new', bucket_type: 'NEW', inactive: false, track_count: 10 },
    { id: 'b-old', bucket_type: 'OLD', inactive: false, track_count: 5 },
    {
      id: 'b-stage',
      bucket_type: 'STAGING',
      inactive: false,
      track_count: 0,
      category_id: 'cat-1',
      category_name: 'Big Room',
    },
  ],
  ...overrides,
});

describe('lastCurateLocation', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it('round-trips per styleId', () => {
    writeLastCurateLocation('style-1', 'block-1', 'b-new');
    expect(readLastCurateLocation('style-1')).toMatchObject({
      blockId: 'block-1',
      bucketId: 'b-new',
    });
  });

  it('returns null for unknown styleId', () => {
    expect(readLastCurateLocation('unknown')).toBeNull();
  });

  it('keeps separate entries per style', () => {
    writeLastCurateLocation('style-1', 'b1', 'bk1');
    writeLastCurateLocation('style-2', 'b2', 'bk2');
    expect(readLastCurateLocation('style-1')?.blockId).toBe('b1');
    expect(readLastCurateLocation('style-2')?.blockId).toBe('b2');
  });

  it('stamps updatedAt on write', () => {
    writeLastCurateLocation('style-1', 'block-1', 'b-new');
    const stored = readLastCurateLocation('style-1');
    expect(stored?.updatedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it('clears the entry for a single style', () => {
    writeLastCurateLocation('style-1', 'b1', 'bk1');
    writeLastCurateLocation('style-2', 'b2', 'bk2');
    clearLastCurateLocation('style-1');
    expect(readLastCurateLocation('style-1')).toBeNull();
    expect(readLastCurateLocation('style-2')?.blockId).toBe('b2');
  });

  it('returns null + clears entry when stored JSON is corrupt', () => {
    localStorage.setItem(LAST_CURATE_LOCATION_KEY, 'not-json');
    expect(readLastCurateLocation('style-1')).toBeNull();
    expect(localStorage.getItem(LAST_CURATE_LOCATION_KEY)).toBeNull();
  });

  it('round-trips lastCurateStyle', () => {
    writeLastCurateStyle('style-7');
    expect(readLastCurateStyle()).toBe('style-7');
  });

  it('isStaleLocation: true when block status is FINALIZED', () => {
    expect(
      isStaleLocation({ blockId: 'block-1', bucketId: 'b-new' }, mkBlock({ status: 'FINALIZED' })),
    ).toBe(true);
  });

  it('isStaleLocation: true when bucketId no longer in block.buckets', () => {
    expect(isStaleLocation({ blockId: 'block-1', bucketId: 'gone' }, mkBlock())).toBe(true);
  });

  it('isStaleLocation: true when bucket is STAGING (not source-eligible)', () => {
    expect(isStaleLocation({ blockId: 'block-1', bucketId: 'b-stage' }, mkBlock())).toBe(true);
  });

  it('isStaleLocation: false on healthy IN_PROGRESS source bucket', () => {
    expect(isStaleLocation({ blockId: 'block-1', bucketId: 'b-new' }, mkBlock())).toBe(false);
  });

  it('exposes the storage keys for tests / migrations', () => {
    expect(LAST_CURATE_LOCATION_KEY).toBe('clouder.lastCurateLocation');
    expect(LAST_CURATE_STYLE_KEY).toBe('clouder.lastCurateStyle');
  });
});
