import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { usePolling } from '../usePolling';
import { setSessionKeepAlive } from '../../../../auth/sessionKeepAlive';

// The device poll calls Spotify; once its token expires, a 401 there calls
// /auth/refresh and wakes Aurora. A hidden idle tab must not poll.

let visibility: DocumentVisibilityState = 'visible';
Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility });

describe('usePolling', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    visibility = 'visible';
    setSessionKeepAlive(false);
  });

  it('ticks on the interval while the tab is visible', () => {
    const fn = vi.fn();
    renderHook(() => usePolling(fn, { enabled: true, intervalMs: 1000 }));
    vi.advanceTimersByTime(3000);
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it('skips ticks while the tab is hidden and idle', () => {
    const fn = vi.fn();
    renderHook(() => usePolling(fn, { enabled: true, intervalMs: 1000 }));
    visibility = 'hidden';
    vi.advanceTimersByTime(3000);
    expect(fn).not.toHaveBeenCalled();
  });

  it('keeps ticking in a hidden tab while music plays', () => {
    const fn = vi.fn();
    renderHook(() => usePolling(fn, { enabled: true, intervalMs: 1000 }));
    visibility = 'hidden';
    setSessionKeepAlive(true);
    vi.advanceTimersByTime(2000);
    expect(fn).toHaveBeenCalledTimes(2);
  });
});
