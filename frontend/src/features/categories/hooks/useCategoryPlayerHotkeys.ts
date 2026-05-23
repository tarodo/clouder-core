import { useEffect } from 'react';

export interface UseCategoryPlayerHotkeysArgs {
  active: boolean;
  playlistCount: number;
  onTogglePlayPause: () => void;
  onPrev: () => void;
  onNext: () => void;
  onSeekPct: (p: number) => void;
  onTogglePlaylist: (index: number) => void;
  onUndo: () => void;
}

const SEEK_PCT: Record<string, number> = {
  KeyA: 0,
  KeyS: 0.2,
  KeyD: 0.4,
  KeyF: 0.6,
  KeyG: 0.8,
};

// <input> types that are widgets, not text entry — they should NOT suppress
// shortcuts (e.g. a Mantine Chip is a focusable <input type="checkbox">).
const NON_EDITABLE_INPUT_TYPES = new Set([
  'checkbox',
  'radio',
  'button',
  'submit',
  'reset',
  'file',
  'range',
  'color',
  'image',
]);

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag === 'INPUT') {
    const type = (target as HTMLInputElement).type.toLowerCase();
    return !NON_EDITABLE_INPUT_TYPES.has(type);
  }
  if (target.isContentEditable) return true;
  return false;
}

function digitIndex(code: string): number | null {
  if (code === 'Digit0') return 9;
  const m = /^Digit([1-9])$/.exec(code);
  return m ? Number(m[1]) - 1 : null;
}

export function useCategoryPlayerHotkeys(args: UseCategoryPlayerHotkeysArgs): void {
  const {
    active,
    playlistCount,
    onTogglePlayPause,
    onPrev,
    onNext,
    onSeekPct,
    onTogglePlaylist,
    onUndo,
  } = args;

  useEffect(() => {
    if (!active) return;
    const handler = (event: KeyboardEvent) => {
      if (isEditable(event.target)) return;

      if (event.code === 'Space') {
        event.preventDefault();
        onTogglePlayPause();
        return;
      }
      if (event.code === 'KeyJ') {
        event.preventDefault();
        onPrev();
        return;
      }
      if (event.code === 'KeyK') {
        event.preventDefault();
        onNext();
        return;
      }
      if (event.code === 'KeyU') {
        event.preventDefault();
        onUndo();
        return;
      }
      const pct = SEEK_PCT[event.code];
      if (pct != null) {
        event.preventDefault();
        onSeekPct(pct);
        return;
      }
      const idx = digitIndex(event.code);
      if (idx != null) {
        if (idx < playlistCount) {
          event.preventDefault();
          onTogglePlaylist(idx);
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [
    active,
    playlistCount,
    onTogglePlayPause,
    onPrev,
    onNext,
    onSeekPct,
    onTogglePlaylist,
    onUndo,
  ]);
}
