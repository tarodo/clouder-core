import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { CopyPlaylistButton } from '../CopyPlaylistButton';
import type { PlaylistTrack } from '../../lib/playlistTypes';

const writeText = vi.fn().mockResolvedValue(undefined);

beforeEach(() => {
  writeText.mockClear();
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

describe('CopyPlaylistButton', () => {
  it('copies the playlist as JSON to the clipboard on click', async () => {
    render(
      <W>
        <CopyPlaylistButton playlistName="My set" tracks={oneTrack} />
      </W>,
    );

    await userEvent.click(screen.getByRole('button', { name: /copy playlist/i }));

    expect(writeText).toHaveBeenCalledTimes(1);
    const call = writeText.mock.calls[0];
    expect(call).toBeDefined();
    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    const parsed = JSON.parse(call![0] as string);
    expect(parsed.playlist).toBe('My set');
    expect(parsed.track_count).toBe(1);
    expect(parsed.tracks[0].beatport_url).toBe(
      'https://www.beatport.com/track/strobe/123456',
    );
    expect(parsed.tracks[0].spotify_url).toBe('https://open.spotify.com/track/sp1');
  });

  it('is disabled when the playlist has no tracks', () => {
    render(
      <W>
        <CopyPlaylistButton playlistName="Empty" tracks={[]} />
      </W>,
    );
    expect(screen.getByRole('button', { name: /copy playlist/i })).toBeDisabled();
  });
});
