import { describe, it, expect } from 'vitest';
import { findNextPlayable } from '../skipNullSpotifyId';

const tA = { id: 'A', spotify_id: 'spA' } as { id: string; spotify_id: string | null };
const tB = { id: 'B', spotify_id: null } as typeof tA;
const tC = { id: 'C', spotify_id: null } as typeof tA;
const tD = { id: 'D', spotify_id: 'spD' } as typeof tA;

describe('findNextPlayable', () => {
  it('returns same index when current is playable', () => {
    expect(findNextPlayable([tA, tB, tD], 0, +1)).toBe(0);
  });
  it('skips null spotify_id forward', () => {
    expect(findNextPlayable([tA, tB, tC, tD], 1, +1)).toBe(3);
  });
  it('skips null spotify_id backward', () => {
    expect(findNextPlayable([tA, tB, tC, tD], 2, -1)).toBe(0);
  });
  it('returns null when all tracks ahead are null', () => {
    expect(findNextPlayable([tA, tB, tC], 1, +1)).toBeNull();
  });
  it('returns null on empty list', () => {
    expect(findNextPlayable([], 0, +1)).toBeNull();
  });
});
