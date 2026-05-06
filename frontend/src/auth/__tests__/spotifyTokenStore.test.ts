import { describe, it, expect, beforeEach, vi } from 'vitest';
import { spotifyTokenStore } from '../spotifyTokenStore';

describe('spotifyTokenStore', () => {
  beforeEach(() => {
    spotifyTokenStore.set(null);
  });

  it('starts null', () => {
    expect(spotifyTokenStore.get()).toBeNull();
  });

  it('round-trips set/get', () => {
    spotifyTokenStore.set('abc');
    expect(spotifyTokenStore.get()).toBe('abc');
  });

  it('clears via set(null)', () => {
    spotifyTokenStore.set('abc');
    spotifyTokenStore.set(null);
    expect(spotifyTokenStore.get()).toBeNull();
  });

  it('does not write to localStorage', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem');
    spotifyTokenStore.set('abc');
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});
