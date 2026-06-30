import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { testTheme } from '../../../test/theme';
import '../../../i18n';
import type { CategoryTrack } from '../hooks/useCategoryTracks';

// vi.hoisted ensures these are available when vi.mock factories run (hoisted).
const { removeAsync } = vi.hoisted(() => ({
  removeAsync: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../hooks/useRemoveTrackOptimistic', () => ({
  useRemoveTrackOptimistic: () => ({ mutateAsync: removeAsync }),
}));
vi.mock('../hooks/useAddTrackToCategory', () => ({
  useAddTrackToCategory: () => ({ mutateAsync: vi.fn() }),
}));
vi.mock('../hooks/useMoveTrackBetweenCategories', () => ({
  useMoveTrackBetweenCategories: () => ({ mutateAsync: vi.fn() }),
  MovePartialError: class extends Error {},
}));
vi.mock('../hooks/useCategoriesByStyle', () => ({
  useCategoriesByStyle: () => ({ data: { items: [] } }),
}));
vi.mock('./AddToPlaylistSubmenu', () => ({
  AddToPlaylistSubmenu: () => null,
}));

import { telemetry } from '../../../lib/telemetry/sdk';
import { TrackRowActions } from './TrackRowActions';

const TRACK: CategoryTrack = {
  id: 'trk-1',
  title: 'Test Track',
  mix_name: null,
  artists: [],
  label: null,
  bpm: null,
  length_ms: null,
  publish_date: null,
  spotify_release_date: null,
  isrc: null,
  spotify_id: null,
  release_type: null,
  is_ai_suspected: false,
  used_in_playlist: false,
  added_at: '2026-01-01T00:00:00Z',
  source_triage_block_id: null,
  tags: [],
};

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <MantineProvider theme={testTheme}>
      <Notifications />
      <QueryClientProvider client={qc}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>
  );
}

describe('TrackRowActions telemetry', () => {
  let trackSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    trackSpy = vi.spyOn(telemetry, 'track');
    removeAsync.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('emits removed_from_category on successful remove', async () => {
    const user = userEvent.setup();
    render(
      <Wrapper>
        <TrackRowActions track={TRACK} currentCategoryId="cat-9" styleId="sty-1" />
      </Wrapper>,
    );

    await user.click(screen.getByRole('button', { name: /Track actions/i }));
    const menu = await screen.findByRole('menu');
    await user.click(within(menu).getByRole('menuitem', { name: /Remove from category/i }));

    await waitFor(() => expect(removeAsync).toHaveBeenCalled());
    expect(trackSpy).toHaveBeenCalledWith('track_categorized', {
      track_id: 'trk-1',
      category_key: 'cat-9',
      action: 'removed_from_category',
    });
  });

  it('does NOT emit on remove failure', async () => {
    removeAsync.mockRejectedValueOnce(new Error('network error'));
    const user = userEvent.setup();
    render(
      <Wrapper>
        <TrackRowActions track={TRACK} currentCategoryId="cat-9" styleId="sty-1" />
      </Wrapper>,
    );

    await user.click(screen.getByRole('button', { name: /Track actions/i }));
    const menu = await screen.findByRole('menu');
    await user.click(within(menu).getByRole('menuitem', { name: /Remove from category/i }));

    await waitFor(() => expect(removeAsync).toHaveBeenCalled());
    expect(trackSpy).not.toHaveBeenCalledWith('track_categorized', expect.objectContaining({ action: 'removed_from_category' }));
  });
});
