import { describe, it, expect, beforeEach, vi } from 'vitest';
import { undoStack, useUndoStack } from '../useUndoStack';
import { renderHook, act } from '@testing-library/react';

beforeEach(() => {
  undoStack.clear();
});

describe('undoStack', () => {
  it('push then peek returns the entry', () => {
    const undo = vi.fn();
    undoStack.push({ id: 'a', label: 'Added', undo });
    expect(undoStack.peek()?.id).toBe('a');
  });

  it('replaces previous entry on push', () => {
    undoStack.push({ id: 'a', label: 'A', undo: vi.fn() });
    undoStack.push({ id: 'b', label: 'B', undo: vi.fn() });
    expect(undoStack.peek()?.id).toBe('b');
  });

  it('popAndRun invokes undo and clears', async () => {
    const undo = vi.fn(() => Promise.resolve());
    undoStack.push({ id: 'a', label: 'A', undo });
    await undoStack.popAndRun();
    expect(undo).toHaveBeenCalledOnce();
    expect(undoStack.peek()).toBeNull();
  });

  it('popAndRun on empty is a no-op', async () => {
    await expect(undoStack.popAndRun()).resolves.toBeUndefined();
  });

  it('subscribers receive notifications on push/pop', () => {
    const cb = vi.fn();
    const unsub = undoStack.subscribe(cb);
    undoStack.push({ id: 'a', label: 'A', undo: vi.fn() });
    expect(cb).toHaveBeenCalledTimes(1);
    unsub();
    undoStack.push({ id: 'b', label: 'B', undo: vi.fn() });
    expect(cb).toHaveBeenCalledTimes(1);
  });
});

describe('useUndoStack hook', () => {
  it('reactively returns the current entry', () => {
    const { result } = renderHook(() => useUndoStack());
    expect(result.current.entry).toBeNull();
    act(() => undoStack.push({ id: 'x', label: 'X', undo: vi.fn() }));
    expect(result.current.entry?.id).toBe('x');
  });
});
