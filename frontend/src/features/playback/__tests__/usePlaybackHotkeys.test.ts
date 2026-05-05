import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { usePlaybackHotkeys } from '../usePlaybackHotkeys';

function fireKey(opts: { code: string; key?: string; shift?: boolean }) {
  const ev = new KeyboardEvent('keydown', {
    code: opts.code,
    key: opts.key ?? '',
    shiftKey: opts.shift ?? false,
    bubbles: true,
  });
  window.dispatchEvent(ev);
}

describe('usePlaybackHotkeys', () => {
  it('Space → togglePlayPause', () => {
    const togglePlayPause = vi.fn();
    renderHook(() =>
      usePlaybackHotkeys({
        onTogglePlayPause: togglePlayPause,
        onPrev: vi.fn(),
        onNext: vi.fn(),
        onSeekRelative: vi.fn(),
        onSeekPct: vi.fn(),
      }),
    );
    fireKey({ code: 'Space' });
    expect(togglePlayPause).toHaveBeenCalled();
  });

  it('Shift+J → -10s, Shift+K → +10s', () => {
    const onSeekRelative = vi.fn();
    renderHook(() =>
      usePlaybackHotkeys({
        onTogglePlayPause: vi.fn(),
        onPrev: vi.fn(),
        onNext: vi.fn(),
        onSeekRelative,
        onSeekPct: vi.fn(),
      }),
    );
    fireKey({ code: 'KeyJ', shift: true });
    expect(onSeekRelative).toHaveBeenLastCalledWith(-10_000);
    fireKey({ code: 'KeyK', shift: true });
    expect(onSeekRelative).toHaveBeenLastCalledWith(10_000);
  });

  it('A/S/D/F/G → seekPct 0/0.2/0.4/0.6/0.8', () => {
    const onSeekPct = vi.fn();
    renderHook(() =>
      usePlaybackHotkeys({
        onTogglePlayPause: vi.fn(),
        onPrev: vi.fn(),
        onNext: vi.fn(),
        onSeekRelative: vi.fn(),
        onSeekPct,
      }),
    );
    ['KeyA', 'KeyS', 'KeyD', 'KeyF', 'KeyG'].forEach((c) => fireKey({ code: c }));
    expect(onSeekPct.mock.calls.map((c) => c[0])).toEqual([0, 0.2, 0.4, 0.6, 0.8]);
  });

  it('plain J → onPrev (post-swap convention)', () => {
    const onPrev = vi.fn();
    const onNext = vi.fn();
    renderHook(() =>
      usePlaybackHotkeys({
        onTogglePlayPause: vi.fn(),
        onPrev,
        onNext,
        onSeekRelative: vi.fn(),
        onSeekPct: vi.fn(),
      }),
    );
    fireKey({ code: 'KeyJ' });
    expect(onPrev).toHaveBeenCalled();
    fireKey({ code: 'KeyK' });
    expect(onNext).toHaveBeenCalled();
  });

  it('ignores keys when target is <input>', () => {
    const cb = vi.fn();
    renderHook(() =>
      usePlaybackHotkeys({
        onTogglePlayPause: cb,
        onPrev: vi.fn(),
        onNext: vi.fn(),
        onSeekRelative: vi.fn(),
        onSeekPct: vi.fn(),
      }),
    );
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    const ev = new KeyboardEvent('keydown', { code: 'Space', bubbles: true });
    Object.defineProperty(ev, 'target', { value: input });
    window.dispatchEvent(ev);
    expect(cb).not.toHaveBeenCalled();
    document.body.removeChild(input);
  });
});
