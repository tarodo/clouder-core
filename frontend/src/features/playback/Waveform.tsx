import { useElementSize } from '@mantine/hooks';
import { useMemo, useState, type CSSProperties, type PointerEvent } from 'react';
import classes from './Waveform.module.css';
import { barHeights } from './lib/waveform';

// A 3px bar every 4px, whole pixels: no bar renders thicker than its neighbours.
const PITCH = 4;
const MIN_BARS = 40;
// Bars under the pointer grow a little: most at the pointer (+18%), fading over ~8 bars a side.
const GROW = 0.18;
const REACH = 8;
const SPREAD = 3;
const KEY_STEP_MS = 5000;

const clock = (ms: number) => {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

export interface WaveformProps {
  /** Loudness per bin, 0..1 (decodeWaveform). null = no waveform: an even row of short bars. */
  loudness: readonly number[] | null;
  /** The short bars without the caption, while the waveform loads. */
  loading?: boolean;
  positionMs: number;
  durationMs: number;
  disabled?: boolean;
  ariaLabel: string;
  emptyLabel: string;
  style?: CSSProperties;
  /** Commits a seek: on release of a click or a drag, or per arrow key. */
  onSeek: (ms: number) => void;
}

/**
 * The player's scrub bar drawn as the track's loudness. A drag previews the position and
 * seeks once on release, so a page scroll that starts on the bars (pointercancel) never seeks.
 */
export function Waveform({
  loudness,
  loading = false,
  positionMs,
  durationMs,
  disabled = false,
  ariaLabel,
  emptyLabel,
  style,
  onSeek,
}: WaveformProps) {
  const { ref, width } = useElementSize();
  const count = Math.max(MIN_BARS, Math.floor((width + 1) / PITCH));
  const span = count * PITCH - 1;
  const heights = useMemo(() => (loudness ? barHeights(loudness, count) : null), [loudness, count]);
  const [hoverMs, setHoverMs] = useState<number | null>(null);
  const [dragMs, setDragMs] = useState<number | null>(null);

  const duration = Math.max(1, durationMs);
  const shownMs = Math.min(dragMs ?? positionMs, duration);
  const played = Math.floor((shownMs / duration) * count);
  const hoverBar = hoverMs === null ? null : Math.min(count - 1, Math.floor((hoverMs / duration) * count));

  const msAt = (e: PointerEvent<HTMLDivElement>) => {
    const left = e.currentTarget.getBoundingClientRect().left;
    return Math.max(0, Math.min(1, (e.clientX - left) / span)) * duration;
  };

  return (
    <div
      ref={ref}
      className={classes.wave}
      role="slider"
      aria-label={ariaLabel}
      aria-valuemin={0}
      aria-valuemax={durationMs}
      aria-valuenow={Math.round(shownMs)}
      aria-valuetext={clock(shownMs)}
      aria-disabled={disabled || undefined}
      tabIndex={disabled ? -1 : 0}
      data-disabled={disabled || undefined}
      style={style}
      onPointerMove={(e) => {
        if (disabled) return;
        const ms = msAt(e);
        setHoverMs(ms);
        if (dragMs !== null) setDragMs(ms);
      }}
      onPointerLeave={() => {
        if (dragMs === null) setHoverMs(null);
      }}
      onPointerDown={(e) => {
        if (disabled) return;
        e.currentTarget.setPointerCapture?.(e.pointerId);
        const ms = msAt(e);
        setDragMs(ms);
        setHoverMs(ms);
      }}
      onPointerUp={(e) => {
        if (dragMs === null) return;
        const ms = msAt(e);
        setDragMs(null);
        if (e.pointerType !== 'mouse') setHoverMs(null);
        onSeek(ms);
      }}
      onPointerCancel={() => {
        setDragMs(null);
        setHoverMs(null);
      }}
      onKeyDown={(e) => {
        const step = e.key === 'ArrowRight' ? KEY_STEP_MS : e.key === 'ArrowLeft' ? -KEY_STEP_MS : 0;
        if (!step || disabled) return;
        e.preventDefault();
        onSeek(Math.max(0, Math.min(duration, positionMs + step)));
      }}
    >
      {Array.from({ length: count }, (_, i) => {
        const d = hoverBar === null ? Infinity : i - hoverBar;
        const grow =
          Math.abs(d) <= REACH ? 1 + GROW * Math.exp(-(d * d) / (2 * SPREAD * SPREAD)) : null;
        return (
          <i
            key={i}
            className={classes.bar}
            data-played={i < played || undefined}
            data-ahead={(hoverBar !== null && i >= played && i <= hoverBar) || undefined}
            style={
              {
                height: heights ? `${heights[i]}%` : '22%',
                ...(grow === null ? {} : { '--grow': String(grow) }),
              } as CSSProperties
            }
          />
        );
      })}
      {hoverMs !== null && !disabled ? (
        <span
          className={classes.tip}
          data-flat={!heights || undefined}
          style={{ left: Math.min(span - 18, Math.max(18, (hoverMs / duration) * span)) }}
        >
          {clock(hoverMs)}
        </span>
      ) : null}
      {!loudness && !loading ? <span className={classes.empty}>{emptyLabel}</span> : null}
    </div>
  );
}
