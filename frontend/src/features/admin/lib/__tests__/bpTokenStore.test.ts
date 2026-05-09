import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { bpTokenStore, useBpToken } from '../bpTokenStore';

describe('bpTokenStore', () => {
  it('stores, returns, and clears the token', () => {
    bpTokenStore.clear();
    expect(bpTokenStore.get()).toBeNull();
    bpTokenStore.set('abc');
    expect(bpTokenStore.get()).toBe('abc');
    bpTokenStore.clear();
    expect(bpTokenStore.get()).toBeNull();
  });

  it('useBpToken re-renders on changes', () => {
    bpTokenStore.clear();
    const { result } = renderHook(() => useBpToken());
    expect(result.current).toBeNull();
    act(() => bpTokenStore.set('xyz'));
    expect(result.current).toBe('xyz');
    act(() => bpTokenStore.clear());
    expect(result.current).toBeNull();
  });
});
