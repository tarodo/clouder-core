import { useEffect, useRef } from 'react';

interface PollingOptions {
  enabled: boolean;
  intervalMs: number;
}

/**
 * Calls `fn` every `intervalMs` while `enabled`, plus on every `window` focus.
 * Always invokes the latest `fn` (no stale closures).
 */
export function usePolling(fn: () => void, { enabled, intervalMs }: PollingOptions): void {
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (!enabled) return;
    const tick = () => fnRef.current();
    const id = window.setInterval(tick, intervalMs);
    const onFocus = () => fnRef.current();
    window.addEventListener('focus', onFocus);
    return () => {
      window.clearInterval(id);
      window.removeEventListener('focus', onFocus);
    };
  }, [enabled, intervalMs]);
}
