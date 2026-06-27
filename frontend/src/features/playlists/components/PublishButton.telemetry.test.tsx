import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { telemetry } from '../../../lib/telemetry/sdk';
import { PublishButton } from './PublishButton';
import type { Playlist, PublishResult } from '../lib/playlistTypes';

const RESULT: PublishResult = {
  spotify_playlist_id: 'spl', spotify_url: 'https://x', skipped_tracks: [],
  cover_failed: false, published_at: '2026-01-01',
};
const mutateAsync = vi.fn().mockResolvedValue(RESULT);
vi.mock('../hooks/usePublishPlaylist', () => ({
  usePublishPlaylist: () => ({ mutateAsync, isPending: false }),
}));

const playlist = { id: 'pl-1', name: 'P', track_count: 2, spotify_playlist_id: null } as Playlist;

describe('PublishButton telemetry', () => {
  beforeEach(() => vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true'));
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    mutateAsync.mockClear();
  });

  it('emits playlist_publish(spotify) with track_ids + skipped_count from the result', async () => {
    const spy = vi.spyOn(telemetry, 'track');
    render(
      <MantineProvider>
        <Notifications />
        <PublishButton playlist={playlist} trackIds={['t1', 't2']} />
      </MantineProvider>,
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
          target: 'spotify',
        }),
      ),
    );
  });
});
