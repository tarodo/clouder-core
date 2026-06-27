// frontend/src/features/curate/hooks/useCurateHotkeys.ts
import { useEffect } from 'react';
import { useMediaQuery } from '@mantine/hooks';
import { isEditableTarget } from '../../../lib/isEditableTarget';
import { useTelemetry } from '../../../lib/telemetry/hooks';
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

export function useCurateHotkeys(args: UseCurateHotkeysArgs): void {
  const isMobile = useMediaQuery('(max-width: 64em)');
  const telemetry = useTelemetry();
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
        telemetry.track('hotkey_used', { hotkey_code: 'Slash', action: 'open_help', source: 'curate' });
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
          telemetry.track('hotkey_used', { hotkey_code: 'KeyU', action: 'undo', source: 'curate' });
          onUndo();
          return;
        case 'KeyL':
          // Silenced while help overlay is open: the overlay shows hotkey
          // hints, toggling Force underneath would change semantics the
          // user is actively reading. KeyU has no such guard because undo
          // is a non-stateful action.
          if (overlayOpen) return;
          event.preventDefault();
          telemetry.track('hotkey_used', { hotkey_code: 'KeyL', action: 'toggle_force', source: 'curate' });
          onToggleForce();
          return;
        // KeyJ / KeyK are handled by usePlaybackHotkeys (F6) — it calls
        // playback.controls.prev/next, which round-trips cursor via
        // onCursorChange so F5's reducer stays in sync. Binding them here
        // too caused double-fire and SDK-state interference.
        case 'KeyQ': {
          event.preventDefault();
          const b = byTechType(buckets, 'NEW');
          if (b) {
            telemetry.track('hotkey_used', { hotkey_code: event.code, action: 'assign_destination', source: 'curate' });
            onAssign(b.id);
          }
          return;
        }
        case 'KeyW': {
          event.preventDefault();
          const b = byTechType(buckets, 'OLD');
          if (b) {
            telemetry.track('hotkey_used', { hotkey_code: event.code, action: 'assign_destination', source: 'curate' });
            onAssign(b.id);
          }
          return;
        }
        case 'KeyE': {
          event.preventDefault();
          const b = byTechType(buckets, 'NOT');
          if (b) {
            telemetry.track('hotkey_used', { hotkey_code: event.code, action: 'assign_destination', source: 'curate' });
            onAssign(b.id);
          }
          return;
        }
        case 'KeyZ': {
          event.preventDefault();
          const b = byDiscard(buckets);
          if (b) {
            telemetry.track('hotkey_used', { hotkey_code: event.code, action: 'assign_destination', source: 'curate' });
            onAssign(b.id);
          }
          return;
        }
        default: {
          const slot = DIGIT_CODES[event.code];
          if (slot !== undefined) {
            event.preventDefault();
            const b = byPosition(buckets, slot);
            if (b) {
              telemetry.track('hotkey_used', { hotkey_code: event.code, action: 'assign_destination', source: 'curate' });
              onAssign(b.id);
            }
          }
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [
    isMobile,
    telemetry,
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
