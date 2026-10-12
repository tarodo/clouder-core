import { useEffect, useRef } from 'react';
import { sessionKeepAlive } from '../../../auth/sessionKeepAlive';

interface PollingOptions {
  enabled: boolean;
  intervalMs: number;
}

/**
 * Calls `fn` every `intervalMs` while `enabled`, plus on every `window` focus.
 * Always invokes the latest `fn` (no stale closures). Interval ticks pause in
 * a hidden tab with no music: the poll's Spotify 401 would call /auth/refresh
 * and wake Aurora; the focus listener catches up when the user returns.
 */
export function usePolling(fn: () => void, { enabled, intervalMs }: PollingOptions): void {
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (!enabled) return;
    const tick = () => {
      if (document.visibilityState === 'hidden' && !sessionKeepAlive()) return;
      fnRef.current();
    };
    const id = window.setInterval(tick, intervalMs);
    const onFocus = () => fnRef.current();
    window.addEventListener('focus', onFocus);
    return () => {
      window.clearInterval(id);
      window.removeEventListener('focus', onFocus);
    };
  }, [enabled, intervalMs]);
}
