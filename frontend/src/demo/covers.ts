/**
 * Twenty abstract release covers for the demo, drawn as SVG: no files, no network.
 * Five motifs × four palettes; the same index always gives the same picture.
 */

export const DEMO_COVER_COUNT = 20;

type Palette = readonly [bg: string, a: string, b: string, c: string];

const PALETTES: readonly Palette[] = [
  ['#0b1026', '#3b82f6', '#f472b6', '#fde68a'], // night neon
  ['#1c0f0a', '#ea580c', '#facc15', '#fef3c7'], // ember
  ['#03201a', '#10b981', '#a3e635', '#ecfccb'], // canopy
  ['#170b2e', '#8b5cf6', '#22d3ee', '#f5f3ff'], // ultraviolet
];

const f = (n: number) => n.toFixed(1);

function rings([bg, a, b, c]: Palette, v: number): string {
  const cx = 230 + (v % 3) * 70;
  const cy = 260 + (v % 2) * 80;
  const circles = Array.from({ length: 11 }, (_, k) => {
    const r = 300 - k * 26;
    const color = [a, b, c][k % 3];
    return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${color}" stroke-width="${9 - (k % 4) * 2}" opacity="${f(0.35 + (k % 3) * 0.2)}"/>`;
  }).join('');
  return `<rect width="600" height="600" fill="${bg}"/>${circles}<circle cx="${cx}" cy="${cy}" r="22" fill="${c}"/>`;
}

function stripes([bg, a, b, c]: Palette, v: number): string {
  const angle = v % 2 ? 32 : -32;
  const bands = Array.from({ length: 14 }, (_, k) => {
    const x = -300 + k * 90;
    const width = 24 + ((k * 7 + v) % 5) * 12;
    const color = [a, b, c][(k + v) % 3];
    return `<rect x="${x}" y="-300" width="${width}" height="1200" fill="${color}" opacity="${f(0.55 + ((k + v) % 3) * 0.15)}"/>`;
  }).join('');
  return (
    `<rect width="600" height="600" fill="${bg}"/>` +
    `<g transform="rotate(${angle} 300 300)">${bands}</g>` +
    `<circle cx="${180 + (v % 3) * 120}" cy="${400 - (v % 2) * 200}" r="110" fill="${bg}"/>` +
    `<circle cx="${180 + (v % 3) * 120}" cy="${400 - (v % 2) * 200}" r="70" fill="${c}"/>`
  );
}

function dots([bg, a, b]: Palette, v: number): string {
  const fx = 150 + (v % 3) * 150;
  const fy = 450 - (v % 2) * 300;
  const cells: string[] = [];
  for (let i = 0; i < 15; i++) {
    for (let j = 0; j < 15; j++) {
      const x = 20 + i * 40;
      const y = 20 + j * 40;
      const d = Math.hypot(x - fx, y - fy) / 600;
      const r = Math.max(1.5, 17 * (1 - d));
      cells.push(`<circle cx="${x}" cy="${y}" r="${f(r)}" fill="${(i + j) % 2 ? a : b}"/>`);
    }
  }
  return `<rect width="600" height="600" fill="${bg}"/>${cells.join('')}`;
}

function waves([bg, a, b, c]: Palette, v: number): string {
  const layers = Array.from({ length: 6 }, (_, k) => {
    const base = 170 + k * 75;
    const amp = 28 + ((k + v) % 3) * 16;
    const phase = (v + k) * 0.9;
    let d = `M0 600 L0 ${f(base)}`;
    for (let x = 0; x <= 600; x += 20) {
      d += ` L${x} ${f(base + amp * Math.sin(x / 70 + phase))}`;
    }
    d += ' L600 600 Z';
    return `<path d="${d}" fill="${[a, b, c][k % 3]}" opacity="${f(0.45 + k * 0.08)}"/>`;
  }).join('');
  return (
    `<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${bg}"/><stop offset="1" stop-color="${a}"/></linearGradient></defs>` +
    `<rect width="600" height="600" fill="url(#g)"/>${layers}`
  );
}

function orbs([bg, a, b, c]: Palette, v: number): string {
  const blobs = [a, b, c]
    .map((color, k) => {
      const cx = 120 + ((v * 97 + k * 173) % 360);
      const cy = 120 + ((v * 61 + k * 211) % 360);
      return `<circle cx="${cx}" cy="${cy}" r="${170 - k * 25}" fill="${color}" opacity="0.85"/>`;
    })
    .join('');
  return (
    `<defs><filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="55"/></filter></defs>` +
    `<rect width="600" height="600" fill="${bg}"/><g filter="url(#blur)">${blobs}</g>` +
    `<rect x="60" y="500" width="120" height="6" fill="${c}"/>`
  );
}

const MOTIFS = [rings, stripes, dots, waves, orbs];
const cache = new Map<number, string>();

/** The i-th cover (0 ≤ i < 20) as a data URI an <img> can show. */
export function demoCover(i: number): string {
  const index = ((i % DEMO_COVER_COUNT) + DEMO_COVER_COUNT) % DEMO_COVER_COUNT;
  const hit = cache.get(index);
  if (hit) return hit;
  const palette = PALETTES[index % PALETTES.length] as Palette;
  const motif = MOTIFS[
    Math.floor(index / PALETTES.length) % MOTIFS.length
  ] as (typeof MOTIFS)[number];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 600" width="600" height="600">${motif(palette, index)}</svg>`;
  const uri = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  cache.set(index, uri);
  return uri;
}
