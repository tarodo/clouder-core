import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { telemetry } from '../../../lib/telemetry/sdk';
import { PublishYtMusicButton } from './PublishYtMusicButton';
import type { Playlist, YtmusicPublishResult } from '../lib/playlistTypes';

const RESULT: YtmusicPublishResult = {
  ytmusic_playlist_id: 'ypl', ytmusic_url: 'https://music.youtube.com/x',
  skipped_tracks: [], cover_failed: false, published_at: '2026-01-01',
};
const mutateAsync = vi.fn().mockResolvedValue(RESULT);
vi.mock('../hooks/usePublishYtmusic', () => ({
  usePublishYtmusic: () => ({ mutateAsync, isPending: false }),
}));
// PublishYtMusicButton gates handleClick on me.data.ytmusic_connected — must be connected.
vi.mock('../../../api/queries/useMe', () => ({
  useMe: () => ({ data: { ytmusic_connected: true } }),
}));

const playlist = { id: 'pl-1', name: 'P', track_count: 2, ytmusic_playlist_id: null } as Playlist;

describe('PublishYtMusicButton telemetry', () => {
  beforeEach(() => vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true'));
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    mutateAsync.mockClear();
  });

  it('emits playlist_publish(ytmusic) with track_ids + skipped_count from the result', async () => {
    const spy = vi.spyOn(telemetry, 'track');
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MantineProvider>
          <Notifications />
          <PublishYtMusicButton playlist={playlist} trackIds={['t1', 't2']} />
        </MantineProvider>
      </QueryClientProvider>,
    );
    await userEvent.click(screen.getByRole('button'));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        'playlist_publish',
        expect.objectContaining({
          track_ids: ['t1', 't2'],
          playlist_id: 'pl-1',
          track_count: 2,
          skipped_count: 0,
          target: 'ytmusic',
        }),
      ),
    );
  });
});
