import { useCallback, useEffect, useRef } from 'react';

/**
 * Per F6-10: scrub commits use `onChangeEnd` for the final commit and a
 * `delayMs` (default 100ms) debounce on `onChange` for in-flight updates.
 *
 * - `onChange(ms)` schedules a deferred `onSeekMs(ms)` call, replacing any
 *   pending one. Used while the user is dragging.
 * - `onChangeEnd(ms)` cancels any pending debounce and commits `onSeekMs(ms)`
 *   synchronously. Used when the drag ends.
 */
export function useScrubDebounce(
  onSeekMs: (ms: number) => void,
  delayMs: number = 100,
): { onChange: (ms: number) => void; onChangeEnd: (ms: number) => void } {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clear any pending timer on unmount so we don't fire seeks after the
  // component is gone.
  useEffect(() => {
    return () => {
      if (timerRef.current != null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  const onChange = useCallback(
    (ms: number) => {
      if (timerRef.current != null) {
        clearTimeout(timerRef.current);
      }
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        onSeekMs(ms);
      }, delayMs);
    },
    [onSeekMs, delayMs],
  );

  const onChangeEnd = useCallback(
    (ms: number) => {
      if (timerRef.current != null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      onSeekMs(ms);
    },
    [onSeekMs],
  );

  return { onChange, onChangeEnd };
}
