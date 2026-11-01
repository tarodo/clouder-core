import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { testTheme } from '../../../test/theme';
import { ConnectedPlayerCard } from '../../playback/TrackPlayer';

const playback = vi.hoisted(() => ({
  controls: {
    togglePlayPause: vi.fn(),
    prev: vi.fn(),
    next: vi.fn(),
    seekMs: vi.fn(),
    play: vi.fn(),
  },
  queue: { source: null, tracks: [], cursor: 0, status: 'playing' },
  track: { current: null, positionMs: 0, durationMs: 300000 },
  sdk: { ready: true, error: null },
  devices: { active: null, cloderTabId: null, open: vi.fn() },
}));
vi.mock('../../playback/usePlayback', () => ({ usePlayback: () => playback }));

const track = {
  id: 't2',
  title: 'Harbor',
  artists: 'Art',
  duration_ms: 300000,
  spotify_id: 'sp2',
  cover_url: null,
};

function renderCard(extra: Record<string, unknown> = {}) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MantineProvider theme={testTheme}>
        <MemoryRouter>
          <ConnectedPlayerCard track={track} {...extra} />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const before = (a: Element, b: Element) =>
  !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe('similar link in every player', () => {
  it('sits left of the Spotify link and opens the similar page', () => {
    renderCard();
    const similar = screen.getByRole('link', { name: /similar tracks/i });
    const spotify = screen.getByRole('link', { name: /spotify/i });
    expect(similar.getAttribute('href')).toBe('/similar/t2');
    expect(before(similar, spotify)).toBe(true);
  });

  it('keeps a caller action (curate fire) first', () => {
    renderCard({ topActions: <button type="button">Fire</button> });
    const fire = screen.getByRole('button', { name: 'Fire' });
    expect(before(fire, screen.getByRole('link', { name: /similar tracks/i }))).toBe(true);
  });
});
