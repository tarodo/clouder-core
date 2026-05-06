import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { act } from 'react';
import { usePolling } from '../lib/usePolling';

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('does not call fn when enabled=false', () => {
    const fn = vi.fn();
    renderHook(() => usePolling(fn, { enabled: false, intervalMs: 1000 }));
    act(() => { vi.advanceTimersByTime(5000); });
    expect(fn).not.toHaveBeenCalled();
  });

  it('calls fn at every interval when enabled', () => {
    const fn = vi.fn();
    renderHook(() => usePolling(fn, { enabled: true, intervalMs: 1000 }));
    act(() => { vi.advanceTimersByTime(1000); });
    expect(fn).toHaveBeenCalledTimes(1);
    act(() => { vi.advanceTimersByTime(2000); });
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it('cleans up on unmount', () => {
    const fn = vi.fn();
    const { unmount } = renderHook(() => usePolling(fn, { enabled: true, intervalMs: 500 }));
    act(() => { vi.advanceTimersByTime(500); });
    expect(fn).toHaveBeenCalledTimes(1);
    unmount();
    act(() => { vi.advanceTimersByTime(5000); });
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('swaps interval when intervalMs changes', () => {
    const fn = vi.fn();
    const { rerender } = renderHook(
      ({ ms }: { ms: number }) => usePolling(fn, { enabled: true, intervalMs: ms }),
      { initialProps: { ms: 1000 } },
    );
    act(() => { vi.advanceTimersByTime(1000); });
    expect(fn).toHaveBeenCalledTimes(1);
    rerender({ ms: 200 });
    act(() => { vi.advanceTimersByTime(600); });
    // 3 ticks at 200ms after rerender
    expect(fn).toHaveBeenCalledTimes(4);
  });

  it('fires fn on window focus event when enabled', () => {
    const fn = vi.fn();
    renderHook(() => usePolling(fn, { enabled: true, intervalMs: 1000 }));
    act(() => { window.dispatchEvent(new Event('focus')); });
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('does not fire on focus when disabled', () => {
    const fn = vi.fn();
    renderHook(() => usePolling(fn, { enabled: false, intervalMs: 1000 }));
    act(() => { window.dispatchEvent(new Event('focus')); });
    expect(fn).not.toHaveBeenCalled();
  });
});
