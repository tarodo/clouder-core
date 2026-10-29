import { Skeleton } from '@mantine/core';
import { createContext, useContext, useEffect, type ReactNode } from 'react';

const GhostContext = createContext(false);

/** A block that is still loading renders its real markup with placeholder data inside an `on`
 * scope: each <Ghost> in it shows as a skeleton bar of its content's exact size, the rest
 * (titles, labels) stays as is, so the block is as big as the loaded one and nothing moves
 * when the data lands. The scope is inert while on. The wrapper is always there (display:
 * contents), so the subtree is not remounted when the data comes. */
export function GhostScope({ on, children }: { on: boolean; children: ReactNode }) {
  return (
    <GhostContext.Provider value={on}>
      <div style={{ display: 'contents' }} inert={on || undefined} aria-busy={on || undefined}>
        {children}
      </div>
    </GhostContext.Provider>
  );
}

/** Data-dependent content: a bar of its own size inside an active GhostScope, else itself.
 * `block` for content that fills its row (inputs, progress bars). */
export function Ghost({ children, block = false }: { children: ReactNode; block?: boolean }) {
  const on = useContext(GhostContext);
  if (!on) return children;
  // A flex box, like the Stack / Group the content sits in: an inline child (a link, a
  // button) is laid out as a block there too, margins and all, with no line box around it.
  return (
    <Skeleton
      visible
      width={block ? '100%' : 'fit-content'}
      radius="sm"
      aria-hidden
      style={{ display: 'flex', flexDirection: 'column' }}
    >
      {children}
    </Skeleton>
  );
}

/** True inside an active GhostScope: for markup that differs while loading (no links). */
export function useGhost(): boolean {
  return useContext(GhostContext);
}

/** `value` once known; before that the value last seen under `key` in this browser, else
 * `fallback`. A loading list draws as many ghost rows as it had last time. */
export function useRemembered(key: string, value: number | undefined, fallback: number): number {
  const storageKey = `ghost:${key}`;
  useEffect(() => {
    if (value === undefined) return;
    try {
      localStorage.setItem(storageKey, String(value));
    } catch {
      // private mode / blocked storage: the fallback will do
    }
  }, [storageKey, value]);
  if (value !== undefined) return value;
  try {
    const stored = localStorage.getItem(storageKey);
    const n = stored === null ? NaN : Number(stored);
    return Number.isInteger(n) && n >= 0 ? n : fallback;
  } catch {
    return fallback;
  }
}
