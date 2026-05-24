/**
 * Browser-mode layout check: the cover must be a square sized to the meta
 * panel's content-column height (Group align="stretch" + a square cover that
 * fills the row height). flexbox + aspect-ratio + height:100% interactions only
 * resolve in a real layout engine, so this lives in the browser harness.
 */
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
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
  track_count: 42,
  status: 'active',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-05-01T00:00:00Z',
};

describe('PlaylistMetaPanel — cover matches content height (browser)', () => {
  test('cover is square and as tall as the content block', async () => {
    const qc = new QueryClient();
    const { container } = render(
      <QueryClientProvider client={qc}>
        <MantineProvider defaultColorScheme="light">
          <div style={{ width: 700 }}>
            <PlaylistMetaPanel playlist={playlist} onPatch={vi.fn(async () => {})} />
          </div>
        </MantineProvider>
      </QueryClientProvider>,
    );

    const group = container.querySelector('.mantine-Group-root') as HTMLElement;
    expect(group).not.toBeNull();
    const content = group.children[1] as HTMLElement; // the content Stack column

    // The cover is sized via a ResizeObserver on the content block, so wait for
    // it to settle, then assert it is square and matches the content height.
    await vi.waitFor(() => {
      const cover = container.querySelector('.mantine-Avatar-root') as HTMLElement;
      const c = cover.getBoundingClientRect();
      const k = content.getBoundingClientRect();
      expect(c.height).toBeGreaterThan(160); // taller than the old fixed 160px cover
      expect(Math.abs(c.width - c.height)).toBeLessThan(2); // square
      expect(Math.abs(c.height - k.height)).toBeLessThan(4); // matches content height
    });
  });
});
