/**
 * Browser-mode layout check: the header is two rows beside a small square cover, so the track
 * list below gets the room. Only a real layout engine measures this.
 */
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { page } from 'vitest/browser';
import '../../../../i18n';
import { PlaylistMetaPanel } from '../PlaylistMetaPanel';
import type { Playlist } from '../../lib/playlistTypes';

const playlist: Playlist = {
  id: 'p1',
  user_id: 'u1',
  name: 'Peak Time Techno',
  description:
    'A longer description that wraps over a couple of lines so the content column is clearly taller than the old 160px cover and we can verify the cover grows to match it.',
  is_public: false,
  cover_s3_key: null,
  cover_url: null,
  cover_uploaded_at: null,
  spotify_playlist_id: null,
  last_published_at: null,
  needs_republish: false,
  ytmusic_playlist_id: null,
  ytmusic_last_published_at: null,
  ytmusic_needs_republish: false,
  track_count: 42,
  status: 'active',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-05-01T00:00:00Z',
};

describe('PlaylistMetaPanel — compact header (browser)', () => {
  test('a small square cover; publish actions share the title row', async () => {
    await page.viewport(1440, 900);
    const qc = new QueryClient();
    const { container } = render(
      <QueryClientProvider client={qc}>
        <MantineProvider defaultColorScheme="light">
          <div style={{ width: 1200 }} data-testid="box">
            <PlaylistMetaPanel
              playlist={playlist}
              onPatch={vi.fn(async () => {})}
              publishSlot={<button type="button">Publish</button>}
            />
          </div>
        </MantineProvider>
      </QueryClientProvider>,
    );

    const header = screen.getByTestId('box').firstElementChild as HTMLElement; // the panel's root
    const cover = container.querySelector('.mantine-Avatar-root')!.getBoundingClientRect();
    expect(Math.abs(cover.width - cover.height)).toBeLessThan(2); // square
    expect(cover.height).toBeLessThanOrEqual(100);
    // was ~200px (cover sized to five rows); now the name, the stats, a two-line description
    expect(header.getBoundingClientRect().height).toBeLessThanOrEqual(120);

    const title = screen.getByRole('heading', { level: 1 }).getBoundingClientRect();
    const publish = screen.getByRole('button', { name: 'Publish' }).getBoundingClientRect();
    const mid = publish.top + publish.height / 2;
    expect(mid).toBeGreaterThan(title.top);
    expect(mid).toBeLessThan(title.bottom);
  });

  // A long name next to wide publish buttons: the buttons drop under the name instead of running
  // off the edge, and the rename pencil stays beside the name instead of taking a row.
  test('a long name: one line, the pencil beside it, the actions wrap inside the header', async () => {
    await page.viewport(1440, 900);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MantineProvider defaultColorScheme="light">
          <div style={{ width: 1000 }} data-testid="box">
            <PlaylistMetaPanel
              playlist={{ ...playlist, name: 'cLoudER : S6 :: DnB :: 032 :: Red Shift' }}
              onPatch={vi.fn(async () => {})}
              publishSlot={
                <div style={{ display: 'flex', gap: 12 }}>
                  {['Re-publish to Spotify', 'Re-publish to YT Music', 'Copy playlist'].map((n) => (
                    <button key={n} type="button" style={{ width: 250, flexShrink: 0 }}>
                      {n}
                    </button>
                  ))}
                </div>
              }
            />
          </div>
        </MantineProvider>
      </QueryClientProvider>,
    );
    const box = screen.getByTestId('box').getBoundingClientRect();
    const title = screen.getByRole('heading', { level: 1 }).getBoundingClientRect();
    const pencil = screen.getByRole('button', { name: /rename/i }).getBoundingClientRect();
    expect(title.height).toBeLessThan(45); // one line
    const mid = pencil.top + pencil.height / 2;
    expect(mid).toBeGreaterThan(title.top);
    expect(mid).toBeLessThan(title.bottom);
    expect(screen.getByRole('button', { name: 'Copy playlist' }).getBoundingClientRect().right).toBeLessThanOrEqual(
      box.right,
    );
  });

  test('phone: the actions take a full-width row under the cover, not a narrow column', async () => {
    await page.viewport(390, 844);
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <MantineProvider defaultColorScheme="light">
          <div style={{ width: 358 }}>
            <PlaylistMetaPanel
              playlist={playlist}
              onPatch={vi.fn(async () => {})}
              publishSlot={<button type="button">Publish</button>}
            />
          </div>
        </MantineProvider>
      </QueryClientProvider>,
    );
    const cover = container.querySelector('.mantine-Avatar-root')!.getBoundingClientRect();
    const publish = screen.getByRole('button', { name: 'Publish' }).getBoundingClientRect();
    expect(publish.top).toBeGreaterThanOrEqual(cover.bottom);
    expect(publish.left).toBeLessThanOrEqual(cover.left + 1);
  });
});
