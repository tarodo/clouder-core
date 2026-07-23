import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { testTheme } from '../../../../test/theme';
import { CopyPlaylistButton } from '../CopyPlaylistButton';
import type { PlaylistExport } from '../../lib/playlistExport';
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

const exportPayload: PlaylistExport = {
  playlist: 'My set',
  track_count: 1,
  tracks: [
    {
      title: 'Strobe',
      mix_name: 'Extended Mix',
      artists: ['deadmau5'],
      label: 'mau5trap',
      isrc: 'US1234567890',
      beatport_url: 'https://www.beatport.com/track/strobe/123456',
      spotify_url: 'https://open.spotify.com/track/sp1',
      youtube_music_url: 'https://music.youtube.com/watch?v=yt1',
      comments: [
        {
          author: 'Alice',
          text: 'Amazing!',
          like_count: 5,
          published_at: '2026-01-10T00:00:00Z',
        },
      ],
    },
  ],
  artists: [{ id: 'a1', name: 'deadmau5', info: { country: 'CA' } }],
  labels: [{ id: 'l1', name: 'mau5trap', info: null }],
};

describe('CopyPlaylistButton', () => {
  it('copies the export payload fetched in a single request', async () => {
    vi.spyOn(client, 'api').mockResolvedValue(exportPayload);

    render(
      <W>
        <CopyPlaylistButton playlistId="p1" trackCount={1} />
      </W>,
    );

    await userEvent.click(screen.getByRole('button', { name: /copy playlist/i }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));

    expect(client.api).toHaveBeenCalledTimes(1);
    expect(client.api).toHaveBeenCalledWith('/playlists/p1/export');

    const call = writeText.mock.calls[0];
    expect(call).toBeDefined();
    const parsed = JSON.parse(call![0] as string);
    expect(parsed.playlist).toBe('My set');
    expect(parsed.track_count).toBe(1);
    expect(parsed.tracks[0].beatport_url).toBe(
      'https://www.beatport.com/track/strobe/123456',
    );
    expect(parsed.tracks[0].comments).toEqual([
      { author: 'Alice', text: 'Amazing!', like_count: 5, published_at: '2026-01-10T00:00:00Z' },
    ]);
    // The enrichment blobs are what make this export worth a server round trip.
    expect(parsed.artists).toEqual([
      { id: 'a1', name: 'deadmau5', info: { country: 'CA' } },
    ]);
    expect(parsed.labels).toEqual([{ id: 'l1', name: 'mau5trap', info: null }]);
  });

  it('shows an error notification and does NOT copy when the api call fails', async () => {
    vi.spyOn(client, 'api').mockRejectedValue(new Error('network error'));
    const showSpy = vi.spyOn(notifications, 'show').mockImplementation(() => '');

    render(
      <W>
        <CopyPlaylistButton playlistId="p1" trackCount={1} />
      </W>,
    );

    await userEvent.click(screen.getByRole('button', { name: /copy playlist/i }));

    await waitFor(() =>
      expect(showSpy).toHaveBeenCalledWith(expect.objectContaining({ color: 'red' })),
    );
    expect(writeText).not.toHaveBeenCalled();
  });

  it('shows an error notification when the clipboard write fails', async () => {
    vi.spyOn(client, 'api').mockResolvedValue(exportPayload);
    writeText.mockRejectedValueOnce(new Error('denied'));
    const showSpy = vi.spyOn(notifications, 'show').mockImplementation(() => '');

    render(
      <W>
        <CopyPlaylistButton playlistId="p1" trackCount={1} />
      </W>,
    );

    await userEvent.click(screen.getByRole('button', { name: /copy playlist/i }));

    await waitFor(() =>
      expect(showSpy).toHaveBeenCalledWith(expect.objectContaining({ color: 'red' })),
    );
  });

  it('is disabled when the playlist has no tracks', () => {
    render(
      <W>
        <CopyPlaylistButton playlistId="p1" trackCount={0} />
      </W>,
    );
    expect(screen.getByRole('button', { name: /copy playlist/i })).toBeDisabled();
  });
});
