import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useScrubDebounce } from '../useScrubDebounce';

describe('useScrubDebounce', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('debounces multiple onChange calls and commits the last value after the delay', () => {
    const seek = vi.fn();
    const { result } = renderHook(() => useScrubDebounce(seek, 100));

    act(() => {
      result.current.onChange(10);
      result.current.onChange(20);
      result.current.onChange(30);
    });

    expect(seek).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(120);
    });

    expect(seek).toHaveBeenCalledTimes(1);
    expect(seek).toHaveBeenCalledWith(30);
  });

  it('onChangeEnd commits immediately and cancels any pending debounced call', () => {
    const seek = vi.fn();
    const { result } = renderHook(() => useScrubDebounce(seek, 100));

    act(() => {
      result.current.onChange(10);
      result.current.onChangeEnd(50);
    });

    expect(seek).toHaveBeenCalledTimes(1);
    expect(seek).toHaveBeenCalledWith(50);

    act(() => {
      vi.advanceTimersByTime(200);
    });

    // No additional call from the cancelled debounce.
    expect(seek).toHaveBeenCalledTimes(1);
  });
});
