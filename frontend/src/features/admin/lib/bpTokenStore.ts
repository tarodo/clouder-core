import { useSyncExternalStore } from 'react';

let value: string | null = null;
const listeners = new Set<() => void>();

export const bpTokenStore = {
  get(): string | null {
    return value;
  },
  set(next: string | null): void {
    const normalized = next === '' ? null : next;
    if (value === normalized) return;
    value = normalized;
    listeners.forEach((l) => l());
  },
  clear(): void {
    if (value === null) return;
    value = null;
    listeners.forEach((l) => l());
  },
  subscribe(cb: () => void): () => void {
    listeners.add(cb);
    return () => listeners.delete(cb);
  },
};

export function useBpToken(): string | null {
  return useSyncExternalStore(
    (cb) => bpTokenStore.subscribe(cb),
    bpTokenStore.get,
    bpTokenStore.get,
  );
}
