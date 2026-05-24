import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { usePlayerHotkeys } from '../usePlayerHotkeys';

const callbacks = {
  onTogglePlayPause: vi.fn(),
  onPrev: vi.fn(),
  onNext: vi.fn(),
  onSeekPct: vi.fn(),
  onTogglePlaylist: vi.fn(),
  onUndo: vi.fn(),
};

function press(code: string, opts: Partial<KeyboardEventInit> = {}) {
  window.dispatchEvent(new KeyboardEvent('keydown', { code, ...opts }));
}

beforeEach(() => {
  Object.values(callbacks).forEach((m) => m.mockReset());
});

describe('usePlayerHotkeys', () => {
  it('does nothing when active=false', () => {
    renderHook(() => usePlayerHotkeys({ ...callbacks, active: false, playlistCount: 10 }));
    press('Space');
    expect(callbacks.onTogglePlayPause).not.toHaveBeenCalled();
  });

  it('Space toggles play', () => {
    renderHook(() => usePlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    press('Space');
    expect(callbacks.onTogglePlayPause).toHaveBeenCalledOnce();
  });

  it('J/K trigger prev/next', () => {
    renderHook(() => usePlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    press('KeyJ');
    press('KeyK');
    expect(callbacks.onPrev).toHaveBeenCalledOnce();
    expect(callbacks.onNext).toHaveBeenCalledOnce();
  });

  it('A/S/D/F/G seek to 0/20/40/60/80% (matches curate convention)', () => {
    // G must NOT be 1.0 — seeking to the very end fires the natural-end
    // detector and auto-advances away from the user's track.
    renderHook(() => usePlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    press('KeyA');
    press('KeyS');
    press('KeyD');
    press('KeyF');
    press('KeyG');
    expect(callbacks.onSeekPct).toHaveBeenNthCalledWith(1, 0);
    expect(callbacks.onSeekPct).toHaveBeenNthCalledWith(2, 0.2);
    expect(callbacks.onSeekPct).toHaveBeenNthCalledWith(3, 0.4);
    expect(callbacks.onSeekPct).toHaveBeenNthCalledWith(4, 0.6);
    expect(callbacks.onSeekPct).toHaveBeenNthCalledWith(5, 0.8);
  });

  it('Digit1..Digit9 map to indices 0..8', () => {
    renderHook(() => usePlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    for (let i = 1; i <= 9; i++) press(`Digit${i}`);
    expect(callbacks.onTogglePlaylist).toHaveBeenCalledTimes(9);
    expect(callbacks.onTogglePlaylist).toHaveBeenNthCalledWith(1, 0);
    expect(callbacks.onTogglePlaylist).toHaveBeenNthCalledWith(9, 8);
  });

  it('Digit0 maps to index 9', () => {
    renderHook(() => usePlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    press('Digit0');
    expect(callbacks.onTogglePlaylist).toHaveBeenCalledWith(9);
  });

  it('Digit5 is no-op when only 4 playlists', () => {
    renderHook(() => usePlayerHotkeys({ ...callbacks, active: true, playlistCount: 4 }));
    press('Digit5');
    expect(callbacks.onTogglePlaylist).not.toHaveBeenCalled();
  });

  it('KeyU triggers undo', () => {
    renderHook(() => usePlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    press('KeyU');
    expect(callbacks.onUndo).toHaveBeenCalledOnce();
  });

  it('ignores keydown when target is an input', () => {
    renderHook(() => usePlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.dispatchEvent(new KeyboardEvent('keydown', { code: 'Space', bubbles: true }));
    expect(callbacks.onTogglePlayPause).not.toHaveBeenCalled();
    document.body.removeChild(input);
  });

  it('fires shortcuts when the target is a checkbox input (e.g. a tag chip)', () => {
    renderHook(() => usePlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    document.body.appendChild(checkbox);
    checkbox.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyJ', bubbles: true }));
    expect(callbacks.onPrev).toHaveBeenCalledOnce();
    document.body.removeChild(checkbox);
  });
});
