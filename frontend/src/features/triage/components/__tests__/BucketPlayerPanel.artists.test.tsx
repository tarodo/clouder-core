import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, test, vi, beforeEach } from 'vitest';
import type { BucketTrack } from '../../hooks/useBucketTracks';
import * as client from '../../../../api/client';

vi.mock('../../../playback/usePlayback', () => ({
  usePlayback: () => ({
    track: { current: { id: 't1', title: 'Song', artists: '', cover_url: null, duration_ms: 1, spotify_id: null }, positionMs: 0 },
    queue: { status: 'playing', source: { type: 'bucket', blockId: 'b1', bucketId: 'k1' } },
    sdk: { error: null },
    devices: { list: [], active: null, cloderTabId: null, open: () => {} },
    controls: {
      togglePlayPause: () => {}, prev: () => {}, next: () => {}, play: () => {},
      seekMs: () => {}, seekPct: () => {}, positionMs: 0,
    },
  }),
}));
vi.mock('../../../playback/usePlaybackHotkeys', () => ({ usePlaybackHotkeys: () => {} }));
vi.mock('../../hooks/useTriageBlock', () => ({
  useTriageBlock: () => ({ data: { style_id: 'techno', status: 'DONE', buckets: [] } }),
}));
vi.mock('../../hooks/useBucketDistribute', () => ({ useBucketDistribute: () => () => {} }));

import { BucketPlayerPanel } from '../BucketPlayerPanel';

const track: BucketTrack = {
  track_id: 't1', title: 'Song', mix_name: null, isrc: null, bpm: 128, length_ms: 1000,
  publish_date: null, spotify_release_date: null, spotify_id: null, release_type: null,
  artists: [
    { id: 'a1', name: 'Main Artist', role: 'main' },
    { id: 'a2', name: 'Second', role: 'main' },
  ],
  label_id: 'l1', label_name: 'Label', added_at: '2026-01-01',
};

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider defaultColorScheme="light">
        <MemoryRouter>
          <BucketPlayerPanel blockId="b1" bucketId="k1" items={[track]} />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('BucketPlayerPanel — artists', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
  });

  test('renders every artist as a tile up front', () => {
    renderPanel();
    expect(screen.getAllByRole('link', { name: 'Main Artist' })).toHaveLength(2);
    expect(screen.getAllByRole('link', { name: 'Second' })).toHaveLength(2);
  });

  test('the player names the artists and the label as links to their pages', () => {
    const { container } = renderPanel();
    const player = within(container.querySelector<HTMLElement>('[data-state]')!);
    expect(player.getByRole('link', { name: 'Main Artist' })).toHaveAttribute('href', '/artists/a1');
    expect(player.getByRole('link', { name: 'Second' })).toHaveAttribute('href', '/artists/a2');
    expect(player.getByRole('link', { name: 'Label' })).toHaveAttribute('href', '/labels/l1');
  });
});
