import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../test/theme';
import { Waveform } from '../Waveform';

// jsdom has no PointerEvent: fireEvent.pointer* would drop clientX and pointerType.
if (!('PointerEvent' in window)) {
  class PointerEvent extends MouseEvent {
    pointerId: number;
    pointerType: string;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 0;
      this.pointerType = init.pointerType ?? 'mouse';
    }
  }
  Object.assign(window, { PointerEvent });
}

const LOUD = Array.from({ length: 600 }, (_, i) => (i % 100) / 100);

function renderWave(over: Partial<Parameters<typeof Waveform>[0]> = {}) {
  const onSeek = vi.fn();
  render(
    <MantineProvider theme={testTheme}>
      <Waveform
        loudness={LOUD}
        positionMs={60_000}
        durationMs={300_000}
        ariaLabel="Scrub bar"
        emptyLabel="No waveform"
        onSeek={onSeek}
        {...over}
      />
    </MantineProvider>,
  );
  const wave = screen.getByRole('slider', { name: 'Scrub bar' });
  // jsdom has no layout: 40 bars (the minimum), so the bars span 159px from x = 0.
  const bars = () => [...wave.querySelectorAll('i')];
  return { wave, bars, onSeek };
}

describe('Waveform', () => {
  it('is a slider over the track in ms', () => {
    const { wave } = renderWave();
    expect(wave).toHaveAttribute('aria-valuenow', '60000');
    expect(wave).toHaveAttribute('aria-valuemax', '300000');
    expect(wave).toHaveAttribute('aria-valuetext', '1:00');
  });

  it('colors the bars already played', () => {
    const { bars } = renderWave();
    // 60 s of 300 s = the first 8 of 40 bars
    expect(bars().filter((b) => b.hasAttribute('data-played'))).toHaveLength(8);
    expect(bars()[7]).toHaveAttribute('data-played');
    expect(bars()[8]).not.toHaveAttribute('data-played');
  });

  it('a click seeks to where it lands', () => {
    const { wave, onSeek } = renderWave();
    fireEvent.pointerDown(wave, { clientX: 79.5, pointerId: 1 });
    expect(onSeek).not.toHaveBeenCalled(); // a drag or a scroll may follow
    fireEvent.pointerUp(wave, { clientX: 79.5, pointerId: 1 });
    expect(onSeek).toHaveBeenCalledExactlyOnceWith(150_000);
  });

  it('a drag previews the position and seeks once, on release', () => {
    const { wave, bars, onSeek } = renderWave();
    fireEvent.pointerDown(wave, { clientX: 10, pointerId: 1 });
    fireEvent.pointerMove(wave, { clientX: 159, pointerId: 1 });
    expect(bars().every((b) => b.hasAttribute('data-played'))).toBe(true);
    expect(onSeek).not.toHaveBeenCalled();
    fireEvent.pointerUp(wave, { clientX: 159, pointerId: 1 });
    expect(onSeek).toHaveBeenCalledExactlyOnceWith(300_000);
  });

  it('a gesture the browser takes over (a page scroll) never seeks', () => {
    const { wave, bars, onSeek } = renderWave();
    fireEvent.pointerDown(wave, { clientX: 100, pointerId: 1, pointerType: 'touch' });
    fireEvent.pointerMove(wave, { clientX: 120, pointerId: 1, pointerType: 'touch' });
    fireEvent.pointerCancel(wave, { pointerId: 1, pointerType: 'touch' });
    expect(onSeek).not.toHaveBeenCalled();
    expect(bars().filter((b) => b.hasAttribute('data-played'))).toHaveLength(8);
  });

  it('arrow keys step 5 s', () => {
    const { wave, onSeek } = renderWave();
    fireEvent.keyDown(wave, { key: 'ArrowRight' });
    fireEvent.keyDown(wave, { key: 'ArrowLeft' });
    expect(onSeek.mock.calls).toEqual([[65_000], [55_000]]);
  });

  it('hovering grows the bars under the pointer, at most +18%', () => {
    const { wave, bars } = renderWave();
    fireEvent.pointerMove(wave, { clientX: 79.5, pointerType: 'mouse' });
    const grow = bars().map((b) => Number(b.style.getPropertyValue('--grow') || 1));
    expect(Math.max(...grow)).toBeCloseTo(1.18);
    expect(grow[0]).toBe(1);
    fireEvent.pointerLeave(wave);
    expect(bars().every((b) => !b.style.getPropertyValue('--grow'))).toBe(true);
  });

  it('without a waveform: even short bars and a caption, still seekable', () => {
    const { wave, bars, onSeek } = renderWave({ loudness: null });
    expect(new Set(bars().map((b) => b.style.height))).toEqual(new Set(['22%']));
    expect(screen.getByText('No waveform')).toBeInTheDocument();
    fireEvent.pointerDown(wave, { clientX: 79.5, pointerId: 1 });
    fireEvent.pointerUp(wave, { clientX: 79.5, pointerId: 1 });
    expect(onSeek).toHaveBeenCalledWith(150_000);
  });

  it('while loading: the short bars, no caption', () => {
    renderWave({ loudness: null, loading: true });
    expect(screen.queryByText('No waveform')).not.toBeInTheDocument();
  });

  it('disabled: no seeking', () => {
    const { wave, onSeek } = renderWave({ disabled: true });
    fireEvent.pointerDown(wave, { clientX: 79.5, pointerId: 1 });
    fireEvent.pointerUp(wave, { clientX: 79.5, pointerId: 1 });
    fireEvent.keyDown(wave, { key: 'ArrowRight' });
    expect(onSeek).not.toHaveBeenCalled();
    expect(wave).toHaveAttribute('aria-disabled', 'true');
  });
});
