// frontend/src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { useCurateHotkeys } from '../useCurateHotkeys';
import type { TriageBucket } from '../../../triage/lib/bucketLabels';

vi.mock('@mantine/hooks', async () => {
  const actual = await vi.importActual<typeof import('@mantine/hooks')>('@mantine/hooks');
  return { ...actual, useMediaQuery: vi.fn(() => false) };
});

const stage = (id: string, name: string): TriageBucket => ({
  id,
  bucket_type: 'STAGING',
  inactive: false,
  track_count: 0,
  category_id: `c-${id}`,
  category_name: name,
});
const tech = (id: string, t: 'NEW' | 'OLD' | 'NOT' | 'DISCARD'): TriageBucket => ({
  id,
  bucket_type: t,
  inactive: false,
  track_count: 0,
});

const buckets: TriageBucket[] = [
  tech('b-new', 'NEW'),
  tech('b-old', 'OLD'),
  tech('b-not', 'NOT'),
  tech('b-disc', 'DISCARD'),
  stage('s1', 'A'),
  stage('s2', 'B'),
  stage('s3', 'C'),
];

function dispatchKey(opts: { code?: string; key?: string }): void {
  const ev = new KeyboardEvent('keydown', {
    code: opts.code ?? '',
    key: opts.key ?? '',
    bubbles: true,
    cancelable: true,
  });
  window.dispatchEvent(ev);
}

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <MantineProvider theme={testTheme}>{children}</MantineProvider>
);

describe('useCurateHotkeys', () => {
  let onAssign: ReturnType<typeof vi.fn>;
  let onUndo: ReturnType<typeof vi.fn>;
  let onSkip: ReturnType<typeof vi.fn>;
  let onPrev: ReturnType<typeof vi.fn>;
  let onOpenOverlay: ReturnType<typeof vi.fn>;
  let onCloseOverlay: ReturnType<typeof vi.fn>;
  let onExit: ReturnType<typeof vi.fn>;
  let onOpenSpotify: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onAssign = vi.fn();
    onUndo = vi.fn();
    onSkip = vi.fn();
    onPrev = vi.fn();
    onOpenOverlay = vi.fn();
    onCloseOverlay = vi.fn();
    onExit = vi.fn();
    onOpenSpotify = vi.fn();
  });
  afterEach(() => vi.restoreAllMocks());

  function mount(overlayOpen: boolean) {
    return renderHook(
      () =>
        useCurateHotkeys({
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
        }),
      { wrapper },
    );
  }

  it('Digit1 calls onAssign with first staging bucket', () => {
    mount(false);
    act(() => dispatchKey({ code: 'Digit1' }));
    expect(onAssign).toHaveBeenCalledWith('s1');
  });

  it('Digit3 calls onAssign with third staging bucket', () => {
    mount(false);
    act(() => dispatchKey({ code: 'Digit3' }));
    expect(onAssign).toHaveBeenCalledWith('s3');
  });

  it('Digit4 with no slot is a no-op', () => {
    mount(false);
    act(() => dispatchKey({ code: 'Digit4' }));
    expect(onAssign).not.toHaveBeenCalled();
  });

  it('KeyQ / KeyW / KeyE map to NEW / OLD / NOT', () => {
    mount(false);
    act(() => dispatchKey({ code: 'KeyQ' }));
    expect(onAssign).toHaveBeenCalledWith('b-new');
    act(() => dispatchKey({ code: 'KeyW' }));
    expect(onAssign).toHaveBeenCalledWith('b-old');
    act(() => dispatchKey({ code: 'KeyE' }));
    expect(onAssign).toHaveBeenCalledWith('b-not');
  });

  it('Digit0 calls onAssign with DISCARD', () => {
    mount(false);
    act(() => dispatchKey({ code: 'Digit0' }));
    expect(onAssign).toHaveBeenCalledWith('b-disc');
  });

  it('KeyU calls onUndo', () => {
    mount(false);
    act(() => dispatchKey({ code: 'KeyU' }));
    expect(onUndo).toHaveBeenCalledTimes(1);
  });

  it('KeyJ / KeyK call onSkip / onPrev', () => {
    mount(false);
    act(() => dispatchKey({ code: 'KeyJ' }));
    expect(onSkip).toHaveBeenCalledTimes(1);
    act(() => dispatchKey({ code: 'KeyK' }));
    expect(onPrev).toHaveBeenCalledTimes(1);
  });

  it('Space calls onOpenSpotify', () => {
    mount(false);
    act(() => dispatchKey({ code: 'Space' }));
    expect(onOpenSpotify).toHaveBeenCalledTimes(1);
  });

  it('? opens the overlay', () => {
    mount(false);
    act(() => dispatchKey({ key: '?' }));
    expect(onOpenOverlay).toHaveBeenCalledTimes(1);
  });

  it('Escape with overlay open calls onCloseOverlay', () => {
    mount(true);
    act(() => dispatchKey({ code: 'Escape' }));
    expect(onCloseOverlay).toHaveBeenCalledTimes(1);
    expect(onExit).not.toHaveBeenCalled();
  });

  it('Escape with overlay closed calls onExit', () => {
    mount(false);
    act(() => dispatchKey({ code: 'Escape' }));
    expect(onExit).toHaveBeenCalledTimes(1);
    expect(onCloseOverlay).not.toHaveBeenCalled();
  });

  it('ignores keystrokes when target is an <input>', () => {
    mount(false);
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    const ev = new KeyboardEvent('keydown', {
      code: 'Digit1',
      bubbles: true,
      cancelable: true,
    });
    Object.defineProperty(ev, 'target', { value: input });
    window.dispatchEvent(ev);
    expect(onAssign).not.toHaveBeenCalled();
    document.body.removeChild(input);
  });

  it('mobile: no listeners bound', async () => {
    const mod = await import('@mantine/hooks');
    (mod.useMediaQuery as unknown as ReturnType<typeof vi.fn>).mockReturnValue(true);
    mount(false);
    act(() => dispatchKey({ code: 'Digit1' }));
    expect(onAssign).not.toHaveBeenCalled();
  });
});
