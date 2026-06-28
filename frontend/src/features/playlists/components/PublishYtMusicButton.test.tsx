import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderApp } from '../../../test/renderApp';
import { PublishYtMusicButton } from './PublishYtMusicButton';
import * as client from '../../../api/client';
import type { Playlist } from '../lib/playlistTypes';

const playlist: Playlist = {
  id: 'p1', user_id: 'u1', name: 'N', description: null, is_public: true,
  cover_s3_key: null, cover_url: null, cover_uploaded_at: null,
  spotify_playlist_id: null, last_published_at: null, needs_republish: false,
  ytmusic_playlist_id: null, ytmusic_last_published_at: null, ytmusic_needs_republish: false,
  track_count: 2, status: 'active', created_at: 't', updated_at: 't',
};

describe('PublishYtMusicButton', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('publishes when already connected', async () => {
    vi.spyOn(client, 'api').mockImplementation(async (path: string) => {
      if (path === '/me') return { ytmusic_connected: true } as never;
      if (path.endsWith('/publish-ytmusic'))
        return {
          ytmusic_playlist_id: 'PLabc',
          ytmusic_url: 'https://music.youtube.com/playlist?list=PLabc',
          skipped_tracks: [], published_at: 't',
        } as never;
      return {} as never;
    });
    renderApp({ initialEntries: ['/'], children: <PublishYtMusicButton playlist={playlist} trackIds={[]} /> });
    await userEvent.click(await screen.findByRole('button', { name: /YT Music/i }));
    await waitFor(() =>
      expect(client.api).toHaveBeenCalledWith('/playlists/p1/publish-ytmusic', expect.any(Object)),
    );
  });

  it('opens connect modal on 412', async () => {
    const { ApiError } = await import('../../../api/error');
    vi.spyOn(client, 'api').mockImplementation(async (path: string) => {
      if (path === '/me') return { ytmusic_connected: false } as never;
      if (path.endsWith('/publish-ytmusic'))
        throw new ApiError('ytmusic_not_authorized', 412, 'no token');
      if (path.endsWith('/device-code'))
        return { device_code: 'dc', user_code: 'ABCD-EFGH', verification_url: 'u', interval: 1, expires_in: 60 } as never;
      return {} as never;
    });
    renderApp({ initialEntries: ['/'], children: <PublishYtMusicButton playlist={playlist} trackIds={[]} /> });
    await userEvent.click(await screen.findByRole('button', { name: /YT Music/i }));
    expect(await screen.findByText('ABCD-EFGH')).toBeInTheDocument();
  });
});
