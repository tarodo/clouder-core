// frontend/src/features/playback/usePlaybackHotkeys.ts
import { useEffect } from 'react';

export interface UsePlaybackHotkeysArgs {
  onTogglePlayPause: () => void;
  onPrev: () => void;
  onNext: () => void;
  onSeekRelative: (deltaMs: number) => void;
  onSeekPct: (p: number) => void;
}

const PCT_KEYS: Record<string, number> = {
  KeyA: 0,
  KeyS: 0.2,
  KeyD: 0.4,
  KeyF: 0.6,
  KeyG: 0.8,
};

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (target.isContentEditable) return true;
  return false;
}

export function usePlaybackHotkeys(args: UsePlaybackHotkeysArgs): void {
  const { onTogglePlayPause, onPrev, onNext, onSeekRelative, onSeekPct } = args;

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (isEditable(event.target)) return;
      if (event.code === 'Space') {
        event.preventDefault();
        onTogglePlayPause();
        return;
      }
      if (event.shiftKey && event.code === 'KeyJ') {
        event.preventDefault();
        onSeekRelative(-10_000);
        return;
      }
      if (event.shiftKey && event.code === 'KeyK') {
        event.preventDefault();
        onSeekRelative(10_000);
        return;
      }
      if (!event.shiftKey && event.code === 'KeyJ') {
        event.preventDefault();
        onPrev();
        return;
      }
      if (!event.shiftKey && event.code === 'KeyK') {
        event.preventDefault();
        onNext();
        return;
      }
      const pct = PCT_KEYS[event.code];
      if (pct != null) {
        event.preventDefault();
        onSeekPct(pct);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onTogglePlayPause, onPrev, onNext, onSeekRelative, onSeekPct]);
}
