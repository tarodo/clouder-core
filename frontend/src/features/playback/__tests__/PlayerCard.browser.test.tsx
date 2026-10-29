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

test('no waveform: the flat bars keep the same height box, the caption sits below them', async () => {
  renderAt(442);
  const caption = await screen.findByText('No waveform');
  const wave = screen.getByRole('slider', { name: 'Scrub bar' });
  expect(box(wave).height).toBe(56);
  const bar = wave.querySelector('i')!.getBoundingClientRect();
  expect(box(caption).top).toBeGreaterThanOrEqual(bar.bottom);
});
