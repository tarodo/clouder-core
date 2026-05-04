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
  onSkip: () => void;
  onPrev: () => void;
  onOpenOverlay: () => void;
  onCloseOverlay: () => void;
  onExit: () => void;
  onOpenSpotify: () => void;
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
    onSkip,
    onPrev,
    onOpenOverlay,
    onCloseOverlay,
    onExit,
    onOpenSpotify,
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
        case 'KeyJ':
          event.preventDefault();
          onSkip();
          return;
        case 'KeyK':
          event.preventDefault();
          onPrev();
          return;
        case 'Space':
          event.preventDefault();
          onOpenSpotify();
          return;
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
        case 'Digit0': {
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
    onSkip,
    onPrev,
    onOpenOverlay,
    onCloseOverlay,
    onExit,
    onOpenSpotify,
  ]);
}
