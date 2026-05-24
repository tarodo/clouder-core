import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
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
          <SortableContext items={['track-1']}>
            {children}
          </SortableContext>
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
  is_ai_suspected: false,
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
  it('renders position, play button (enabled), artists, label, bpm, length, release date, tag pills, and Remove button', async () => {
    const onRemove = vi.fn();
    const onPlay = vi.fn();

    render(
      <W>
        <PlaylistTrackRow
          track={richTrack}
          position={3}
          onRemove={onRemove}
          onPlay={onPlay}
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

    // Artists
    expect(screen.getByText('Ben Klock, Blawan')).toBeInTheDocument();

    // Label
    expect(screen.getByText('Ostgut Ton')).toBeInTheDocument();

    // BPM
    expect(screen.getByText('140')).toBeInTheDocument();

    // Length: 6:30
    expect(screen.getByText('6:30')).toBeInTheDocument();

    // Release date
    expect(screen.getByText('2024-03-15')).toBeInTheDocument();

    // Tag pills
    expect(screen.getByText('Dark')).toBeInTheDocument();
    expect(screen.getByText('Vocal')).toBeInTheDocument();

    // Remove button
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
        />
      </W>,
    );

    const playBtn = screen.getByRole('button', { name: /play track/i });
    expect(playBtn).toBeDisabled();
  });

  it('removes a tag by clicking the colored pill (no × icon)', async () => {
    const onRemoveTag = vi.fn();
    render(
      <W>
        <PlaylistTrackRow
          track={richTrack}
          position={1}
          onRemove={vi.fn()}
          onPlay={vi.fn()}
          onRemoveTag={onRemoveTag}
        />
      </W>,
    );

    // The pill itself is the remove control; there is no separate "×" button.
    expect(screen.queryByText('×')).toBeNull();
    const darkPill = screen.getByRole('button', { name: 'Remove Dark' });
    await userEvent.click(darkPill);
    expect(onRemoveTag).toHaveBeenCalledWith('tg1');
  });
});
