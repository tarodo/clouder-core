import { describe, it, expect } from 'vitest';
import { readFresh, writeFresh } from '../freshUrlState';

describe('freshUrlState', () => {
  it('absent param defaults to true', () => {
    expect(readFresh(new URLSearchParams(''))).toBe(true);
  });
  it('fresh=0 reads as false', () => {
    expect(readFresh(new URLSearchParams('fresh=0'))).toBe(false);
  });
  it('fresh=1 reads as true', () => {
    expect(readFresh(new URLSearchParams('fresh=1'))).toBe(true);
  });
  it('writing true removes the param', () => {
    const next = writeFresh(new URLSearchParams('fresh=0'), true);
    expect(next.has('fresh')).toBe(false);
  });
  it('writing false sets fresh=0', () => {
    const next = writeFresh(new URLSearchParams(''), false);
    expect(next.get('fresh')).toBe('0');
  });
});
