/**
 * wave-1 (GET /tracks/{id}/waveform): base64 of 3 bands (bass, mids, highs) x N time bins
 * of u8 dB, band after band. The player draws one loudness curve, mostly bass (a break is
 * where the bass goes), stretched over the track's own range: its quietest 5% at the
 * bottom, its loudest moment at the top.
 */
export function decodeWaveform(data: string): number[] {
  const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
  const n = Math.floor(bytes.length / 3);
  if (!n) return [];
  const raw = Array.from({ length: n }, (_, i) => 0.75 * bytes[i]! + 0.25 * bytes[n + i]!);
  const sorted = [...raw].sort((a, b) => a - b);
  const lo = sorted[Math.floor(n * 0.05)]!;
  const range = sorted[n - 1]! - lo || 1;
  return raw.map((v) => Math.max(0, Math.min(1, (v - lo) / range)));
}

/** One height per bar (% of the waveform box): the loudest bin under it; the curve deepens the dips. */
export function barHeights(loudness: readonly number[], count: number): number[] {
  const n = loudness.length;
  return Array.from({ length: count }, (_, b) => {
    const from = Math.floor((b / count) * n);
    const to = Math.max(from + 1, Math.floor(((b + 1) / count) * n));
    let v = 0;
    for (let i = from; i < to; i++) v = Math.max(v, loudness[i] ?? 0);
    return 10 + 90 * v ** 1.6;
  });
}
