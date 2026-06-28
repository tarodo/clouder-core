import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { telemetry } from '../../../lib/telemetry/sdk';
import { useCurateHotkeys } from './useCurateHotkeys';

const BUCKETS = [
  { id: 'q', bucket_type: 'NEW', inactive: false, track_count: 0 },
  { id: 'd', bucket_type: 'DISCARD', inactive: false, track_count: 0 },
] as const;

function setup(over: Partial<Parameters<typeof useCurateHotkeys>[0]> = {}) {
  const onAssign = vi.fn();
  const onUndo = vi.fn();
  const onToggleForce = vi.fn();
  const onOpenOverlay = vi.fn();
  renderHook(() =>
    useCurateHotkeys({
      buckets: BUCKETS as never,
      overlayOpen: false,
      onAssign,
      onUndo,
      onOpenOverlay,
      onCloseOverlay: vi.fn(),
      onExit: vi.fn(),
      onToggleForce,
      ...over,
    }),
  );
  return { onAssign, onUndo, onToggleForce, onOpenOverlay };
}

function key(init: KeyboardEventInit) {
  window.dispatchEvent(new KeyboardEvent('keydown', init));
}

describe('useCurateHotkeys telemetry', () => {
  beforeEach(() => vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true'));
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('KeyU emits action=undo and fires onUndo', () => {
    const spy = vi.spyOn(telemetry, 'track');
    const { onUndo } = setup();
    key({ code: 'KeyU' });
    expect(onUndo).toHaveBeenCalled();
    expect(spy).toHaveBeenCalledWith('hotkey_used', { hotkey_code: 'KeyU', action: 'undo', source: 'curate' });
  });

  it('KeyL emits action=toggle_force', () => {
    const spy = vi.spyOn(telemetry, 'track');
    setup();
    key({ code: 'KeyL' });
    expect(spy).toHaveBeenCalledWith('hotkey_used', { hotkey_code: 'KeyL', action: 'toggle_force', source: 'curate' });
  });

  it('KeyQ emits action=assign_destination with the real code', () => {
    const spy = vi.spyOn(telemetry, 'track');
    const { onAssign } = setup();
    key({ code: 'KeyQ' });
    expect(onAssign).toHaveBeenCalledWith('q');
    expect(spy).toHaveBeenCalledWith('hotkey_used', { hotkey_code: 'KeyQ', action: 'assign_destination', source: 'curate' });
  });

  it('"?" emits action=open_help with hotkey_code Slash', () => {
    const spy = vi.spyOn(telemetry, 'track');
    setup();
    key({ key: '?', code: 'Slash' });
    expect(spy).toHaveBeenCalledWith('hotkey_used', { hotkey_code: 'Slash', action: 'open_help', source: 'curate' });
  });

  it('Escape emits nothing (not one of the four actions)', () => {
    const spy = vi.spyOn(telemetry, 'track');
    setup();
    key({ code: 'Escape' });
    expect(spy).not.toHaveBeenCalled();
  });
});
