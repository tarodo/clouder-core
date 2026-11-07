import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DndContext } from '@dnd-kit/core';
import { SortableContext } from '@dnd-kit/sortable';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { PlaylistTrackRow } from '../PlaylistTrackRow';
import type { PlaylistTrack } from '../../lib/playlistTypes';

function W({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  return (
    <MantineProvider theme={testTheme}>
      <QueryClientProvider client={qc}>
        <DndContext>
          <SortableContext items={['track-1']}>{children}</SortableContext>
        </DndContext>
      </QueryClientProvider>
    </MantineProvider>
  );
}

const richTrack: PlaylistTrack = {
  track_id: 'track-1',
  position: 0,
  added_at: '2026-05-12T00:00:00Z',
  title: 'Deep Horizon',
  spotify_id: 'sp123',
  isrc: null,
  length_ms: 390_000, // 6:30
  origin: 'beatport',
  mix_name: 'Original Mix',
  artists: [
    { id: 'a1', name: 'Ben Klock' },
    { id: 'a2', name: 'Blawan' },
  ],
  label: { id: 'l1', name: 'Ostgut Ton' },
  bpm: 140,
  spotify_release_date: '2024-03-15',
  tags: [
    { id: 'tg1', name: 'Dark', color: '#333' },
    { id: 'tg2', name: 'Vocal', color: null },
  ],
};

beforeEach(() => {
  tokenStore.set('TOK');
  server.use(
    http.get('http://localhost/tags', () =>
      HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
    ),
  );
});

describe('PlaylistTrackRow', () => {
  it('shows the YouTube comment count on the meta line, none when it is unknown', () => {
    const { rerender } = render(
      <W>
        <PlaylistTrackRow
          track={{ ...richTrack, comment_count: 12 }}
          position={1}
          onRemove={vi.fn()}
          playlistId="p1"
        />
      </W>,
    );
    expect(screen.getByLabelText('YouTube comments')).toHaveTextContent('12');
    rerender(
      <W>
        <PlaylistTrackRow
          track={{ ...richTrack, comment_count: null }}
          position={1}
          onRemove={vi.fn()}
          playlistId="p1"
        />
      </W>,
    );
    expect(screen.queryByLabelText('YouTube comments')).not.toBeInTheDocument();
  });

  it('renders position, play button (enabled), artists, meta line, tag pills (read-only), and Remove button', async () => {
    const onRemove = vi.fn();
    const onPlay = vi.fn();

    render(
      <W>
        <PlaylistTrackRow
          track={richTrack}
          position={3}
          onRemove={onRemove}
          onPlay={onPlay}
          playlistId="pl1"
        />
      </W>,
    );

    // Position number
    expect(screen.getByText('3.')).toBeInTheDocument();

    // Play button present and ENABLED (spotify_id set), and fires onPlay
    const playBtn = screen.getByRole('button', { name: /play track/i });
    expect(playBtn).toBeInTheDocument();
    expect(playBtn).not.toBeDisabled();
    await userEvent.click(playBtn);
    expect(onPlay).toHaveBeenCalledTimes(1);

    // Title and mix name
    expect(screen.getByText('Deep Horizon')).toBeInTheDocument();
    expect(screen.getByText('Original Mix')).toBeInTheDocument();

    // Artists: each name in its own box, so a long one ends in an ellipsis before its AI badge
    expect(screen.getByText('Ben Klock').parentElement).toHaveTextContent('Ben Klock, Blawan');

    // Meta line: single pipe-joined string
    expect(screen.getByText(/Ostgut Ton \| 140 BPM \| 6:30 \| 2024-03-15/)).toBeInTheDocument();

    // Tag pills present (read-only — no remove button for individual tags)
    expect(screen.getByText('Dark')).toBeInTheDocument();
    expect(screen.getByText('Vocal')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /remove dark/i })).toBeNull();

    // Remove track button (subtle text) fires onRemove
    const removeBtn = screen.getByRole('button', { name: /remove/i });
    expect(removeBtn).toBeInTheDocument();
    await userEvent.click(removeBtn);
    expect(onRemove).toHaveBeenCalledWith(richTrack);

    // No burger / "Track actions" menu
    expect(screen.queryByRole('button', { name: /track actions/i })).toBeNull();
  });

  it('disables the play button when spotify_id is null', () => {
    const noSpotifyTrack: PlaylistTrack = {
      ...richTrack,
      track_id: 'track-1',
      spotify_id: null,
    };

    render(
      <W>
        <PlaylistTrackRow
          track={noSpotifyTrack}
          position={1}
          onRemove={vi.fn()}
          onPlay={vi.fn()}
          playlistId="pl1"
        />
      </W>,
    );

    const playBtn = screen.getByRole('button', { name: /no spotify match/i });
    expect(playBtn).toBeDisabled();
  });

  it('tags are read-only in the list (no remove button on pill)', () => {
    render(
      <W>
        <PlaylistTrackRow
          track={richTrack}
          position={1}
          onRemove={vi.fn()}
          onPlay={vi.fn()}
          playlistId="pl1"
        />
      </W>,
    );

    // Tag text still renders
    expect(screen.getByText('Dark')).toBeInTheDocument();
    // But the pill is NOT an interactive remove button
    expect(screen.queryByRole('button', { name: /remove dark/i })).toBeNull();
  });

  it('renders a Beatport link when beatport_track_id is present', () => {
    const bpTrack: PlaylistTrack = {
      ...richTrack,
      beatport_track_id: '123456',
      beatport_slug: 'deep-horizon',
    };

    render(
      <W>
        <PlaylistTrackRow
          track={bpTrack}
          position={1}
          onRemove={vi.fn()}
          onPlay={vi.fn()}
          playlistId="pl1"
        />
      </W>,
    );

    const link = screen.getByRole('link', { name: /open on beatport/i });
    expect(link).toHaveAttribute('href', 'https://www.beatport.com/track/deep-horizon/123456');
  });

  it('omits the Beatport link when beatport_track_id is absent', () => {
    render(
      <W>
        <PlaylistTrackRow
          track={richTrack}
          position={1}
          onRemove={vi.fn()}
          onPlay={vi.fn()}
          playlistId="pl1"
        />
      </W>,
    );

    expect(screen.queryByRole('link', { name: /open on beatport/i })).toBeNull();
  });
});

describe('PlaylistTrackRow AI badge', () => {
  it.each([
    ['high', ['high']],
    ['medium', ['medium']],
    ['low', ['low']],
    [null, []],
  ] as const)('ai_verdict=%s shows AI badges of levels %j', (verdict, levels) => {
    render(
      <W>
        <PlaylistTrackRow
          track={{ ...richTrack, ai_verdict: verdict }}
          position={1}
          onRemove={vi.fn()}
          onPlay={vi.fn()}
          playlistId="pl1"
        />
      </W>,
    );
    expect(
      screen
        .queryAllByText('AI')
        .map((el) => el.closest('[data-level]')?.getAttribute('data-level')),
    ).toEqual(levels);
  });
});

describe('PlaylistTrackRow AI reputation', () => {
  it('marks the artist and the label', () => {
    const track: PlaylistTrack = {
      ...richTrack,
      artists: [
        { id: 'a', name: 'Artist', ai: { level: 1 as const, ai: 2, checked: 41, total: 300 } },
      ],
      label: {
        id: 'l1',
        name: 'Ostgut Ton',
        ai: { level: 3 as const, ai: 80, checked: 87, total: 869 },
      },
    };
    render(
      <W>
        <PlaylistTrackRow
          track={track}
          position={1}
          onRemove={vi.fn()}
          onPlay={vi.fn()}
          playlistId="pl1"
        />
      </W>,
    );
    expect(screen.getByLabelText('AI level 1')).toBeInTheDocument();
    expect(screen.getByLabelText('AI level 3')).toBeInTheDocument();
  });
});

describe('PlaylistTrackRow on a phone', () => {
  let media: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    media = vi.spyOn(window, 'matchMedia').mockImplementation(
      (query: string) =>
        ({
          matches: query === '(max-width: 64em)',
          media: query,
          onchange: null,
          addListener: vi.fn(),
          removeListener: vi.fn(),
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
          dispatchEvent: vi.fn(),
        }) as unknown as MediaQueryList,
    );
  });
  afterEach(() => media.mockRestore());

  const phoneTrack: PlaylistTrack = {
    ...richTrack,
    beatport_track_id: '123456',
    beatport_slug: 'deep-horizon',
    ytmusic: { status: 'matched', url: 'https://music.youtube.com/watch?v=yt1' },
  };

  it('keeps title, mix, artists and tags; links and Remove go behind the menu', async () => {
    const onRemove = vi.fn();
    render(
      <W>
        <PlaylistTrackRow
          track={phoneTrack}
          position={1}
          onRemove={onRemove}
          onPlay={vi.fn()}
          playlistId="pl1"
        />
      </W>,
    );

    const menu = await screen.findByRole('button', { name: /track actions/i });
    expect(screen.getByText('Deep Horizon')).toBeInTheDocument();
    expect(screen.getByText('Original Mix')).toBeInTheDocument();
    expect(screen.getByText('Ben Klock, Blawan')).toBeInTheDocument();
    expect(screen.getByText('Dark')).toBeInTheDocument();
    // no key / label / BPM / length / date line
    expect(screen.queryByText(/Ostgut Ton/)).toBeNull();
    expect(screen.queryByText(/140 BPM/)).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByRole('button', { name: /^remove$/i })).toBeNull();

    await userEvent.click(menu);
    const dropdown = await screen.findByRole('menu');
    expect(within(dropdown).getByRole('menuitem', { name: /open in spotify/i })).toHaveAttribute(
      'href',
      'https://open.spotify.com/track/sp123',
    );
    expect(within(dropdown).getByRole('menuitem', { name: /open on beatport/i })).toHaveAttribute(
      'href',
      'https://www.beatport.com/track/deep-horizon/123456',
    );
    expect(within(dropdown).getByRole('menuitem', { name: /yt music/i })).toHaveAttribute(
      'href',
      'https://music.youtube.com/watch?v=yt1',
    );
    await userEvent.click(within(dropdown).getByRole('menuitem', { name: /remove/i }));
    expect(onRemove).toHaveBeenCalledWith(phoneTrack);
  });

  it('keeps a YT Music match that needs review in the row', async () => {
    render(
      <W>
        <PlaylistTrackRow
          track={{ ...phoneTrack, ytmusic: { status: 'needs_review' } }}
          position={1}
          onRemove={vi.fn()}
          onPlay={vi.fn()}
          playlistId="pl1"
        />
      </W>,
    );
    await screen.findByRole('button', { name: /track actions/i });
    expect(screen.getByRole('button', { name: /review yt music match/i })).toBeInTheDocument();
  });
});
