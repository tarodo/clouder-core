import { describe, it, expect, beforeEach } from 'vitest';
import {
  readLastVisitedTriageStyle,
  writeLastVisitedTriageStyle,
  LAST_TRIAGE_STYLE_KEY,
} from '../lastVisitedTriageStyle';

describe('lastVisitedTriageStyle', () => {
  beforeEach(() => localStorage.clear());

  it('returns null when nothing stored', () => {
    expect(readLastVisitedTriageStyle()).toBeNull();
  });

  it('round-trips a style id', () => {
    writeLastVisitedTriageStyle('abc-123');
    expect(readLastVisitedTriageStyle()).toBe('abc-123');
  });

  it('uses the documented namespace key', () => {
    expect(LAST_TRIAGE_STYLE_KEY).toBe('clouder.lastTriageStyleId');
  });

  it('is independent of the categories key', () => {
    localStorage.setItem('clouder.lastStyleId', 'cat-style');
    writeLastVisitedTriageStyle('triage-style');
    expect(localStorage.getItem('clouder.lastStyleId')).toBe('cat-style');
    expect(readLastVisitedTriageStyle()).toBe('triage-style');
  });

  it('survives a thrown SecurityError on read', () => {
    const original = Storage.prototype.getItem;
    Storage.prototype.getItem = () => {
      throw new Error('SecurityError');
    };
    try {
      expect(readLastVisitedTriageStyle()).toBeNull();
    } finally {
      Storage.prototype.getItem = original;
    }
  });
});
