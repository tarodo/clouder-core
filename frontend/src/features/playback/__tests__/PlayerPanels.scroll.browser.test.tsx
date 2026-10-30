import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { page } from 'vitest/browser';
import '../../../i18n';
import { clouderTheme } from '../../../theme';
import category from '../../categories/components/CategoryPlayerPanel.module.css';
import entity from '../../library/components/EntityPlayerPanel.module.css';
import playlist from '../../playlists/components/PlaylistPlayerPanel.module.css';
import bucket from '../../triage/components/BucketPlayerPanel.module.css';
import { TrackPlayer } from '../TrackPlayer';

// No msw in the browser runner: the API comes from a mocked api/client.
vi.mock('../../../api/client', () => ({ api: () => Promise.resolve({ waveform: null }) }));

const playback = vi.hoisted(() => ({
  controls: {
    togglePlayPause: vi.fn(),
    prev: vi.fn(),
    next: vi.fn(),
    seekMs: vi.fn(),
    seekPct: vi.fn(),
    play: vi.fn(),
  },
  queue: { source: null, tracks: [], cursor: 0, status: 'paused' },
  track: {
    current: { id: 't1', title: 'Drive Thunder', artists: 'Odessa Marlo', duration_ms: 314000, spotify_id: 'sp1', cover_url: null },
    positionMs: 0,
    durationMs: 314000,
  },
  sdk: { ready: true, error: null },
  devices: { active: null, cloderTabId: null, open: vi.fn() },
}));
vi.mock('../usePlayback', () => ({ usePlayback: () => playback }));

const panels = [
  ['category', category.root],
  ['playlist', playlist.root],
  ['bucket', bucket.root],
  ['entity', entity.root],
] as const;

// The side player panels scroll on their own: at the end of the comments the wheel must not
// start scrolling the track list behind them (scroll chaining).
test.each(panels)('the %s player panel keeps its scroll to itself', async (_name, className) => {
  await page.viewport(1280, 800);
  render(<div className={className} data-testid="panel" />);
  const style = getComputedStyle(screen.getByTestId('panel'));
  expect(style.overflowY).toBe('auto');
  expect(style.overscrollBehaviorY).toBe('contain');
});

describe('a player panel under the page header', () => {
  // Without the page scrolling along, the panel's own end must be reachable: it fits the
  // screen below the header, and grows into the header's room as the page scrolls past it.
  test.each(panels)('the %s panel ends on screen at every page scroll', async (_name, className) => {
    await page.viewport(1280, 800);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MantineProvider theme={clouderTheme}>
          <div style={{ height: 300 }}>Playlist header</div>
          <div style={{ display: 'flex', alignItems: 'flex-start' }}>
            <TrackPlayer className={className} info={null} empty="pick">
              {() => <div style={{ height: 3000 }}>Comments</div>}
            </TrackPlayer>
            <div style={{ height: 5000 }}>Track list</div>
          </div>
        </MantineProvider>
      </QueryClientProvider>,
    );
    const panel = document.querySelector('[data-player]')!;
    const bottom = () => panel.getBoundingClientRect().bottom;
    for (const y of [0, 150, 1000]) {
      window.scrollTo(0, y);
      // the panel's end stays at the screen's bottom edge: never below it, never far above
      await expect.poll(bottom).toBeGreaterThan(window.innerHeight - 20);
      expect(bottom()).toBeLessThanOrEqual(window.innerHeight);
    }
    window.scrollTo(0, 0);
  });
});
