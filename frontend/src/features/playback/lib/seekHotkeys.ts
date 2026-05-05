export function pctToMs(pct: number, durationMs: number): number {
  const clamped = Math.max(0, Math.min(1, pct));
  return Math.round(clamped * durationMs);
}

export function clampMs(ms: number, durationMs: number): number {
  return Math.max(0, Math.min(durationMs, ms));
}
