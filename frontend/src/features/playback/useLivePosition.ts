import { useEffect, useState } from 'react';

/**
 * Interpolates the playback position between authoritative updates (SDK
 * events / seeks). Local to the progress UI so only its consumer re-renders.
 * Re-anchors whenever `positionMs` or `playing` changes; clamps at duration.
 */
export function useLivePosition(positionMs: number, playing: boolean, durationMs: number): number {
  const [anchor, setAnchor] = useState(() => ({ pos: positionMs, at: performance.now(), playing }));
  const [now, setNow] = useState(() => performance.now());

  useEffect(() => {
    const t = performance.now();
    setAnchor({ pos: positionMs, at: t, playing });
    setNow(t);
    if (!playing) return;
    const id = setInterval(() => setNow(performance.now()), 250);
    return () => clearInterval(id);
  }, [positionMs, playing]);

  // Anchor not yet synced with props (render before effect): show the prop as-is.
  if (anchor.pos !== positionMs || anchor.playing !== playing || !playing) return positionMs;
  const live = anchor.pos + Math.max(0, now - anchor.at);
  return durationMs > 0 ? Math.min(durationMs, live) : live;
}
