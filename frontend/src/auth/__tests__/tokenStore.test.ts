import { describe, it, expect, beforeEach } from 'vitest';
import { tokenStore } from '../tokenStore';

describe('tokenStore', () => {
  beforeEach(() => tokenStore.set(null));

  it('returns null when unset', () => {
    expect(tokenStore.get()).toBeNull();
  });

  it('round-trips a token', () => {
    tokenStore.set('abc');
    expect(tokenStore.get()).toBe('abc');
  });

  it('clears with null', () => {
    tokenStore.set('abc');
    tokenStore.set(null);
    expect(tokenStore.get()).toBeNull();
  });
});
