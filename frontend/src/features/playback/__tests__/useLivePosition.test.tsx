import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useLivePosition } from '../useLivePosition';

describe('useLivePosition', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  const setup = (pos: number, playing: boolean, dur = 60000) =>
    renderHook((p) => useLivePosition(p.pos, p.playing, p.dur), {
      initialProps: { pos, playing, dur },
    });

  it('advances ~1s per second while playing', () => {
    const { result } = setup(1000, true);
    act(() => { vi.advanceTimersByTime(3000); });
    expect(result.current).toBeGreaterThanOrEqual(3900);
    expect(result.current).toBeLessThanOrEqual(4100);
  });

  it('stays put when not playing', () => {
    const { result } = setup(1000, false);
    act(() => { vi.advanceTimersByTime(3000); });
    expect(result.current).toBe(1000);
  });

  it('re-anchors on new positionMs', () => {
    const { result, rerender } = setup(1000, true);
    act(() => { vi.advanceTimersByTime(2000); });
    rerender({ pos: 20000, playing: true, dur: 60000 });
    expect(result.current).toBe(20000);
    act(() => { vi.advanceTimersByTime(1000); });
    expect(result.current).toBeGreaterThanOrEqual(20900);
    expect(result.current).toBeLessThanOrEqual(21100);
  });

  it('clamps at duration', () => {
    const { result } = setup(9000, true, 10000);
    act(() => { vi.advanceTimersByTime(5000); });
    expect(result.current).toBe(10000);
  });

  it('freezes on pause', () => {
    const { result, rerender } = setup(1000, true);
    act(() => { vi.advanceTimersByTime(2000); });
    rerender({ pos: 3000, playing: false, dur: 60000 });
    act(() => { vi.advanceTimersByTime(3000); });
    expect(result.current).toBe(3000);
  });
});
