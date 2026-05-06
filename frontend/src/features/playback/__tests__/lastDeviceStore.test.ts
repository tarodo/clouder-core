import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { lastDeviceStore } from '../lib/lastDeviceStore';

const KEY = 'clouder.last_device_id';

describe('lastDeviceStore', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns null when nothing saved', () => {
    expect(lastDeviceStore.get()).toBeNull();
  });

  it('round-trips set/get', () => {
    lastDeviceStore.set('abc-123');
    expect(lastDeviceStore.get()).toBe('abc-123');
    expect(window.localStorage.getItem(KEY)).toBe('abc-123');
  });

  it('clear removes the entry', () => {
    lastDeviceStore.set('abc-123');
    lastDeviceStore.clear();
    expect(lastDeviceStore.get()).toBeNull();
    expect(window.localStorage.getItem(KEY)).toBeNull();
  });

  it('returns null and does not throw when set throws', () => {
    vi.spyOn(window.Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('quota');
    });
    expect(() => lastDeviceStore.set('abc')).not.toThrow();
    // get should still return null because setItem was suppressed
    expect(lastDeviceStore.get()).toBeNull();
  });

  it('returns null when get throws (Safari private mode)', () => {
    vi.spyOn(window.Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('access denied');
    });
    expect(lastDeviceStore.get()).toBeNull();
  });

  it('does not throw when clear throws', () => {
    vi.spyOn(window.Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new DOMException('access denied');
    });
    expect(() => lastDeviceStore.clear()).not.toThrow();
  });
});
