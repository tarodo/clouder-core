import { describe, it, expect } from 'vitest';
import {
  hasPlayerCard,
  contextOf,
  contextDifferent,
} from '../routeContext';

describe('hasPlayerCard', () => {
  it('matches Curate session route', () => {
    expect(hasPlayerCard('/curate/style-1/block-1/bucket-1')).toBe(true);
  });
  it('does not match Curate index/resume routes', () => {
    expect(hasPlayerCard('/curate')).toBe(false);
    expect(hasPlayerCard('/curate/style-1')).toBe(false);
  });
  it('does not match Tracks/Profile/Home', () => {
    expect(hasPlayerCard('/tracks')).toBe(false);
    expect(hasPlayerCard('/profile')).toBe(false);
    expect(hasPlayerCard('/')).toBe(false);
    expect(hasPlayerCard('/triage')).toBe(false);
  });
});

describe('contextOf', () => {
  it('extracts bucket context from Curate session path', () => {
    expect(contextOf('/curate/style-1/blockA/bucketU')).toEqual({
      type: 'bucket',
      blockId: 'blockA',
      bucketId: 'bucketU',
    });
  });
  it('returns null for non-PlayerCard routes', () => {
    expect(contextOf('/tracks')).toBeNull();
  });
});

describe('contextDifferent', () => {
  it('true when bucket differs', () => {
    expect(
      contextDifferent('/curate/s/A/U', '/curate/s/A/V'),
    ).toBe(true);
    expect(
      contextDifferent('/curate/s/A/U', '/curate/s/B/U'),
    ).toBe(true);
  });
  it('false when same bucket', () => {
    expect(contextDifferent('/curate/s/A/U', '/curate/s/A/U')).toBe(false);
  });
  it('false when target is not a PlayerCard route', () => {
    expect(contextDifferent('/curate/s/A/U', '/tracks')).toBe(false);
  });
});
