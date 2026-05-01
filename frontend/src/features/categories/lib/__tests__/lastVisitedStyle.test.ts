import { describe, it, expect, beforeEach } from 'vitest';
import { readLastVisitedStyle, writeLastVisitedStyle, LAST_STYLE_KEY } from '../lastVisitedStyle';

describe('lastVisitedStyle', () => {
  beforeEach(() => localStorage.clear());

  it('returns null when nothing stored', () => {
    expect(readLastVisitedStyle()).toBeNull();
  });

  it('round-trips a style id', () => {
    writeLastVisitedStyle('abc-123');
    expect(readLastVisitedStyle()).toBe('abc-123');
  });

  it('uses the documented namespace key', () => {
    expect(LAST_STYLE_KEY).toBe('clouder.lastStyleId');
  });

  it('survives a thrown SecurityError on read', () => {
    const original = Storage.prototype.getItem;
    Storage.prototype.getItem = () => {
      throw new Error('SecurityError');
    };
    try {
      expect(readLastVisitedStyle()).toBeNull();
    } finally {
      Storage.prototype.getItem = original;
    }
  });

  it('survives a thrown SecurityError on write', () => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = () => {
      throw new Error('QuotaExceededError');
    };
    try {
      expect(() => writeLastVisitedStyle('abc-123')).not.toThrow();
    } finally {
      Storage.prototype.setItem = original;
    }
  });
});
