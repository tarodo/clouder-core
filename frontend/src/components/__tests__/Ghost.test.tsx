import { renderHook } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';
import { useRemembered } from '../Ghost';

afterEach(() => localStorage.clear());

test('a loading list falls back before anything was seen', () => {
  const { result } = renderHook(() => useRemembered('rows', undefined, 3));
  expect(result.current).toBe(3);
});

test('a loading list gets the count it had last time', () => {
  renderHook(() => useRemembered('rows', 7, 3)).unmount();
  const { result } = renderHook(() => useRemembered('rows', undefined, 3));
  expect(result.current).toBe(7);
});

test('a garbage stored value reads as the fallback', () => {
  localStorage.setItem('ghost:rows', 'many');
  const { result } = renderHook(() => useRemembered('rows', undefined, 3));
  expect(result.current).toBe(3);
});
