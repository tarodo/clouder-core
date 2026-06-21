import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { testTheme } from '../../../../test/theme';
import { CopyPlaylistButton } from '../CopyPlaylistButton';
import type { PlaylistTrack } from '../../lib/playlistTypes';
import * as client from '../../../../api/client';

const writeText = vi.fn().mockResolvedValue(undefined);

beforeEach(() => {
  writeText.mockClear();
  vi.restoreAllMocks();
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
  });
});

function W({ children }: { children: React.ReactNode }) {
  return <MantineProvider theme={testTheme}>{children}</MantineProvider>;
}

const oneTrack: PlaylistTrack[] = [
  {
    track_id: 't1',
    position: 0,
    added_at: '2026-01-01T00:00:00Z',
    title: 'Strobe',
    spotify_id: 'sp1',
    isrc: 'US1234567890',
    length_ms: 600000,
    origin: 'beatport',
    mix_name: 'Extended Mix',
    artists: [{ id: 'a1', name: 'deadmau5' }],
    label: { id: 'l1', name: 'mau5trap' },
    bpm: 128,
    spotify_release_date: null,
    is_ai_suspected: false,
    tags: [],
    ytmusic: { status: 'matched', url: 'https://music.youtube.com/watch?v=yt1' },
    beatport_track_id: '123456',
    beatport_slug: 'strobe',
  },
];

const mockCommentsResponse = {
  tracks: [
    {
      track_id: 't1',
      status: 'collected' as const,
      comment_count: 1,
      video_url: 'https://www.youtube.com/watch?v=abc',
      comments: [
        {
          author_name: 'Alice',
          author_avatar_url: null,
          text: 'Amazing!',
          like_count: 5,
          published_at: '2026-01-10T00:00:00Z',
        },
      ],
    },
  ],
  correlation_id: 'test-corr',
};

describe('CopyPlaylistButton', () => {
  it('fetches bulk comments and copies the playlist with comments as JSON', async () => {
    vi.spyOn(client, 'api').mockResolvedValue(mockCommentsResponse);

    render(
      <W>
        <CopyPlaylistButton playlistName="My set" tracks={oneTrack} playlistId="p1" />
      </W>,
    );

    await userEvent.click(screen.getByRole('button', { name: /copy playlist/i }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));

    expect(client.api).toHaveBeenCalledWith('/playlists/p1/comments?platform=youtube');

    const call = writeText.mock.calls[0];
    expect(call).toBeDefined();
    const parsed = JSON.parse(call![0] as string);
    expect(parsed.playlist).toBe('My set');
    expect(parsed.track_count).toBe(1);
    expect(parsed.tracks[0].beatport_url).toBe(
      'https://www.beatport.com/track/strobe/123456',
    );
    expect(parsed.tracks[0].spotify_url).toBe('https://open.spotify.com/track/sp1');
    expect(parsed.tracks[0].comments).toEqual([
      { author: 'Alice', text: 'Amazing!', like_count: 5, published_at: '2026-01-10T00:00:00Z' },
    ]);
  });

  it('shows an error notification and does NOT copy when api call fails', async () => {
    vi.spyOn(client, 'api').mockRejectedValue(new Error('network error'));
    const showSpy = vi.spyOn(notifications, 'show').mockImplementation(() => '');

    render(
      <W>
        <CopyPlaylistButton playlistName="My set" tracks={oneTrack} playlistId="p1" />
      </W>,
    );

    await userEvent.click(screen.getByRole('button', { name: /copy playlist/i }));

    await waitFor(() =>
      expect(showSpy).toHaveBeenCalledWith(
        expect.objectContaining({ color: 'red' }),
      ),
    );
    expect(writeText).not.toHaveBeenCalled();
  });

  it('shows an error notification when the clipboard write fails', async () => {
    vi.spyOn(client, 'api').mockResolvedValue(mockCommentsResponse);
    writeText.mockRejectedValueOnce(new Error('denied'));
    const showSpy = vi.spyOn(notifications, 'show').mockImplementation(() => '');

    render(
      <W>
        <CopyPlaylistButton playlistName="My set" tracks={oneTrack} playlistId="p1" />
      </W>,
    );

    await userEvent.click(screen.getByRole('button', { name: /copy playlist/i }));

    await waitFor(() =>
      expect(showSpy).toHaveBeenCalledWith(
        expect.objectContaining({ color: 'red' }),
      ),
    );
  });

  it('is disabled when the playlist has no tracks', () => {
    render(
      <W>
        <CopyPlaylistButton playlistName="Empty" tracks={[]} playlistId="p1" />
      </W>,
    );
    expect(screen.getByRole('button', { name: /copy playlist/i })).toBeDisabled();
  });
});
