import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useElapsedTime } from '../useElapsedTime';

describe('useElapsedTime', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('returns 0 initially when not running', () => {
    const { result } = renderHook(() => useElapsedTime(false));
    expect(result.current).toBe(0);
  });

  it('increments while running', () => {
    const { result } = renderHook(() => useElapsedTime(true));
    expect(result.current).toBe(0);
    act(() => {
      vi.advanceTimersByTime(1100);
    });
    expect(result.current).toBeGreaterThanOrEqual(1000);
  });

  it('resets to 0 when toggled off', () => {
    const { result, rerender } = renderHook(({ running }) => useElapsedTime(running), {
      initialProps: { running: true },
    });
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(result.current).toBeGreaterThanOrEqual(2000);
    rerender({ running: false });
    expect(result.current).toBe(0);
  });
});
