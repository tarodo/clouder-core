import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import '../../../i18n';
import { clouderTheme } from '../../../theme';
import { PlayerCard } from '../PlayerCard';

const noop = () => {};
const track = {
  id: 't1',
  title: 'Flower Crown feat. Hannelotta',
  artists: 'hannelotta, Matt View',
  duration_ms: 214_000,
  cover_url: null,
  spotify_id: 'x',
};

function renderAt(width: number) {
  render(
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
    </MantineProvider>,
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
