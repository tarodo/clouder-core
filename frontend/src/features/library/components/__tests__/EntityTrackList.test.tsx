import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { EntityTrackList, type EntityTrackListProps } from '../EntityTrackList';
import type { EntityTrack } from '../../hooks/useEntityTracks';

const track: EntityTrack = {
  id: 't1',
  title: 'Harbor',
  mix_name: null,
  artists: [{ id: 'art', name: 'Art', ai: null }],
  label: { id: 'lbl', name: 'Hinterland', ai: null },
  style: { id: 'st', name: 'DnB' },
  bpm: 174,
  length_ms: 300000,
  key_name: null,
  key_camelot: '8A',
  release_date: '2026-10-20',
  spotify_id: 'sp1',
  ai_verdict: null,
  categories: [],
  playlists: [],
};

function renderList(over: Partial<EntityTrackListProps> = {}) {
  render(
    <MantineProvider theme={testTheme}>
      <EntityTrackList
        showLabel
        items={[track]}
        variant="desktop"
        loading={false}
        hasMore={false}
        loadingMore={false}
        onMore={vi.fn()}
        currentTrackId={null}
        playing={false}
        onPlay={vi.fn()}
        onToggle={vi.fn()}
        {...over}
      />
    </MantineProvider>,
  );
}

describe('EntityTrackList columns', () => {
  it('has a style column by default', () => {
    renderList();
    expect(screen.getByRole('columnheader', { name: 'Style' })).toBeInTheDocument();
  });

  it('drops it for a one-style list (similar tracks: the header names the style)', () => {
    renderList({ showStyle: false });
    expect(screen.queryByRole('columnheader', { name: 'Style' })).not.toBeInTheDocument();
    expect(screen.queryByText('DnB')).not.toBeInTheDocument();
  });
});
