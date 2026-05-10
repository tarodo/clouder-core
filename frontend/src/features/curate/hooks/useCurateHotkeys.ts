// frontend/src/features/curate/hooks/useCurateHotkeys.ts
import { useEffect } from 'react';
import { useMediaQuery } from '@mantine/hooks';
import type { TriageBucket } from '../../triage/lib/bucketLabels';
import { byDiscard, byPosition, byTechType } from '../lib/destinationMap';

export interface UseCurateHotkeysArgs {
  buckets: TriageBucket[];
  overlayOpen: boolean;
  onAssign: (toBucketId: string) => void;
  onUndo: () => void;
  onOpenOverlay: () => void;
  onCloseOverlay: () => void;
  onExit: () => void;
  onToggleForce: () => void;
}

const DIGIT_CODES: Record<string, number> = {
  Digit1: 0,
  Digit2: 1,
  Digit3: 2,
  Digit4: 3,
  Digit5: 4,
  Digit6: 5,
  Digit7: 6,
  Digit8: 7,
  Digit9: 8,
};

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (target.isContentEditable) return true;
  return false;
}

export function useCurateHotkeys(args: UseCurateHotkeysArgs): void {
  const isMobile = useMediaQuery('(max-width: 64em)');
  const {
    buckets,
    overlayOpen,
    onAssign,
    onUndo,
    onOpenOverlay,
    onCloseOverlay,
    onExit,
    onToggleForce,
  } = args;

  useEffect(() => {
    if (isMobile) return;
    const handler = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;

      // Help overlay (key form because of layout sensitivity).
      if (event.key === '?') {
        event.preventDefault();
        onOpenOverlay();
        return;
      }

      switch (event.code) {
        case 'Escape':
          event.preventDefault();
          if (overlayOpen) onCloseOverlay();
          else onExit();
          return;
        case 'KeyU':
          event.preventDefault();
          onUndo();
          return;
        case 'KeyL':
          // Silenced while help overlay is open: the overlay shows hotkey
          // hints, toggling Force underneath would change semantics the
          // user is actively reading. KeyU has no such guard because undo
          // is a non-stateful action.
          if (overlayOpen) return;
          event.preventDefault();
          onToggleForce();
          return;
        // KeyJ / KeyK are handled by usePlaybackHotkeys (F6) — it calls
        // playback.controls.prev/next, which round-trips cursor via
        // onCursorChange so F5's reducer stays in sync. Binding them here
        // too caused double-fire and SDK-state interference.
        case 'KeyQ': {
          event.preventDefault();
          const b = byTechType(buckets, 'NEW');
          if (b) onAssign(b.id);
          return;
        }
        case 'KeyW': {
          event.preventDefault();
          const b = byTechType(buckets, 'OLD');
          if (b) onAssign(b.id);
          return;
        }
        case 'KeyE': {
          event.preventDefault();
          const b = byTechType(buckets, 'NOT');
          if (b) onAssign(b.id);
          return;
        }
        case 'KeyZ': {
          event.preventDefault();
          const b = byDiscard(buckets);
          if (b) onAssign(b.id);
          return;
        }
        default: {
          const slot = DIGIT_CODES[event.code];
          if (slot !== undefined) {
            event.preventDefault();
            const b = byPosition(buckets, slot);
            if (b) onAssign(b.id);
          }
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [
    isMobile,
    buckets,
    overlayOpen,
    onAssign,
    onUndo,
    onOpenOverlay,
    onCloseOverlay,
    onExit,
    onToggleForce,
  ]);
}
