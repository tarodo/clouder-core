/**
 * Browser-mode smoke for PublishYtMusicButton: verifies the button renders and
 * that clicking it when not connected opens the YtMusicConnectModal.
 */
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import '../../../i18n';
import type { Playlist } from '../lib/playlistTypes';
import { PublishYtMusicButton } from './PublishYtMusicButton';

vi.mock('../../../api/client', () => ({
  api: vi.fn(async (path: string) => {
    if (path === '/me') return { ytmusic_connected: false };
    if (path.endsWith('/device-code'))
      return {
        device_code: 'dc',
        user_code: 'ABCD-EFGH',
        verification_url: 'https://www.google.com/device',
        interval: 60,
        expires_in: 1800,
      };
    return {};
  }),
}));

const playlist: Playlist = {
  id: 'p1', user_id: 'u1', name: 'N', description: null, is_public: true,
  cover_s3_key: null, cover_url: null, cover_uploaded_at: null,
  spotify_playlist_id: null, last_published_at: null, needs_republish: false,
  ytmusic_playlist_id: null, ytmusic_last_published_at: null, ytmusic_needs_republish: false,
  track_count: 2, status: 'active', created_at: 't', updated_at: 't',
};

describe('PublishYtMusicButton — browser smoke', () => {
  it('renders publish button and opens connect modal when not connected', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MantineProvider defaultColorScheme="light">
          <Notifications />
          <PublishYtMusicButton playlist={playlist} trackIds={[]} />
        </MantineProvider>
      </QueryClientProvider>,
    );

    const btn = await screen.findByRole('button', { name: /YT Music/i });
    expect(btn).toBeVisible();

    await userEvent.click(btn);
    // After clicking while not connected, the connect modal opens and fetches a device code
    expect(await screen.findByText('ABCD-EFGH')).toBeInTheDocument();
  });
});
