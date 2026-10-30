import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import '../../../i18n';
import { clouderTheme } from '../../../theme';
import { PlayerCard } from '../PlayerCard';

// No msw in the browser runner: the waveform route comes from a mocked api/client.
const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));
vi.mock('../../../api/client', () => ({ api: apiMock }));
const WAVE = btoa(
  String.fromCharCode(
    ...Array.from({ length: 1800 }, (_, i) => Math.round(128 + 120 * Math.sin(i / 9))),
  ),
);

const noop = () => {};
const track = {
  id: 't1',
  title: 'Flower Crown feat. Hannelotta',
  artists: 'hannelotta, Matt View',
  duration_ms: 214_000,
  cover_url: null,
  spotify_id: 'x',
};

function renderAt(width: number, waveform: { duration_ms: number; data: string } | null = null) {
  apiMock.mockResolvedValue({ waveform });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MantineProvider theme={clouderTheme}>
        <div style={{ width }}>
          <PlayerCard
            variant="full"
            state="paused"
            track={track as never}
            positionMs={0}
            mixName="Original Mix"
            showTimes
            spotifyHref="https://open.spotify.com/track/x"
            onPlayPause={noop}
            onPrev={noop}
            onNext={noop}
            onRetry={noop}
            onOpenDevicePicker={noop}
            onSeekMs={noop}
          />
        </div>
      </MantineProvider>
    </QueryClientProvider>,
  );
  const title = screen.getByRole('heading', { name: track.title });
  const play = screen.getByRole('button', { name: /play/i });
  const cover = title.closest('.mantine-Paper-root')!.querySelector('[class*="cover"]')!;
  return { title, play, cover, artists: screen.getByText(track.artists) };
}

const box = (el: Element) => el.getBoundingClientRect();

test('a side-panel player (442px) gives the title and artists room: controls go below', () => {
  const { title, play, cover, artists } = renderAt(442);
  expect(box(play).top).toBeGreaterThanOrEqual(box(cover).bottom);
  expect(box(title).width).toBeGreaterThan(200);
  expect(artists.scrollWidth).toBeLessThanOrEqual(artists.clientWidth); // fits, no ellipsis
});

test('a long title wraps onto a second line in a narrow player instead of an ellipsis', () => {
  const { title } = renderAt(442);
  expect(title.scrollWidth).toBeLessThanOrEqual(title.clientWidth);
});

test('a wide player keeps cover, text and controls on one row', () => {
  const { play, cover } = renderAt(900);
  expect(box(play).top).toBeLessThan(box(cover).bottom);
  expect(box(play).bottom).toBeGreaterThan(box(cover).top);
});

test('the waveform: whole-pixel bars, 3px each on a 4px pitch, filling the width', async () => {
  renderAt(442, { duration_ms: 214_000, data: WAVE });
  const wave = screen.getByRole('slider', { name: 'Scrub bar' });
  await waitFor(() => {
    const heights = new Set([...wave.querySelectorAll('i')].map((b) => b.style.height));
    expect(heights.size).toBeGreaterThan(10);
  });
  const bars = [...wave.querySelectorAll('i')].map((b) => b.getBoundingClientRect());
  expect(new Set(bars.map((b) => b.width))).toEqual(new Set([3]));
  const pitches = new Set(bars.slice(1).map((b, i) => b.left - bars[i]!.left));
  expect(pitches).toEqual(new Set([4]));
  const span = bars.at(-1)!.right - bars[0]!.left;
  expect(box(wave).width - span).toBeLessThan(4);
  expect(box(wave).height).toBe(56);
});

test('no waveform: the flat bars keep the same height box, no caption', async () => {
  renderAt(442);
  await waitFor(() => expect(apiMock).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 100)); // the query settles on "none"
  const wave = screen.getByRole('slider', { name: 'Scrub bar' });
  expect(box(wave).height).toBe(56);
  expect(wave.textContent).toBe('');
});

/** Moves the mouse onto *bar*; resolves once the bars by it have lit up. */
async function hover(wave: HTMLElement, bar: Element) {
  const r = box(bar);
  wave.dispatchEvent(
    new PointerEvent('pointermove', {
      bubbles: true,
      clientX: r.left + 1.5,
      clientY: r.top,
      pointerType: 'mouse',
    }),
  );
  await waitFor(() => expect((bar as HTMLElement).style.getPropertyValue('--glow')).toBe('1'));
}

// average channel, 0..255, of an element's background (tokens are oklch, color-mix gives
// color(srgb ...)): a 1px canvas converts either
const level = (el: Element) => {
  const ctx = document.createElement('canvas').getContext('2d')!;
  ctx.fillStyle = getComputedStyle(el).backgroundColor;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return (r! + g! + b!) / 3;
};

test('hover: the bars past the pointer fade from its shade, no cut at the pointer', async () => {
  renderAt(442, { duration_ms: 214_000, data: WAVE });
  const wave = screen.getByRole('slider', { name: 'Scrub bar' });
  await waitFor(() => {
    const heights = new Set([...wave.querySelectorAll('i')].map((b) => b.style.height));
    expect(heights.size).toBeGreaterThan(10);
    expect(wave.querySelectorAll('i').length).toBeGreaterThan(60); // sized to the 442px box
  });
  const bars = [...wave.querySelectorAll('i')];
  const k = 40;
  await hover(wave, bars[k]!);
  const [at, next, mid, far] = [k, k + 1, k + 5, k + 12].map((i) => level(bars[i]!));
  expect(Math.abs(next! - at!)).toBeLessThan(12); // the neighbour keeps nearly the pointer's shade
  expect(next).toBeLessThan(mid!);
  expect(mid).toBeLessThan(far!);
  // and the bar under the pointer grows (+18%), one out of reach does not
  const scale = (i: number) => box(bars[i]!).height / (bars[i] as HTMLElement).offsetHeight;
  await waitFor(() => expect(scale(k)).toBeCloseTo(1.18, 1));
  expect(scale(k + 12)).toBeCloseTo(1, 1); // offsetHeight rounds to whole px
});

test('hover on the flat bars: a smooth hump of a few px, the time clear above it', async () => {
  renderAt(442);
  await waitFor(() => expect(apiMock).toHaveBeenCalled());
  const wave = screen.getByRole('slider', { name: 'Scrub bar' });
  await waitFor(() => expect(wave.querySelectorAll('i').length).toBeGreaterThan(60));
  const bars = [...wave.querySelectorAll('i')];
  const k = 40;
  await hover(wave, bars[k]!);
  await new Promise((r) => setTimeout(r, 300)); // the 140ms grow transition
  const rest = box(bars[k + 12]!).height;
  const rise = (i: number) => (box(bars[i]!).height - rest) / 2; // px each way
  expect(rise(k)).toBeGreaterThan(2.5); // a 1px bump reads as a step, not a hump
  for (let i = k; i < k + 9; i++) expect(rise(i) - rise(i + 1)).toBeLessThan(0.8);
  const tip = wave.querySelector('span')!;
  expect(box(tip).bottom).toBeLessThanOrEqual(box(bars[k]!).top - 3);
});
