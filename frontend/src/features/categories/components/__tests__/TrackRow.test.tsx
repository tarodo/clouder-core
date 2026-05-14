import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider, Table } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { TrackRow } from '../TrackRow';
import type { CategoryTrack } from '../../hooks/useCategoryTracks';

function W({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <MantineProvider theme={testTheme}>
      <Notifications />
      <QueryClientProvider client={qc}>
        <Table><Table.Tbody>{children}</Table.Tbody></Table>
      </QueryClientProvider>
    </MantineProvider>
  );
}

function WMobile({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <MantineProvider theme={testTheme}>
      <Notifications />
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </MantineProvider>
  );
}

const baseTrack: CategoryTrack = {
  id: 't1', title: 't1', mix_name: null, artists: [], label: null,
  bpm: null, length_ms: null, publish_date: null,
  spotify_release_date: null, isrc: null, spotify_id: null,
  release_type: null, is_ai_suspected: false, used_in_playlist: false,
  added_at: '2026-05-01T00:00:00Z', source_triage_block_id: null,
  tags: [{ id: 'tg1', name: 'Vocal', color: '#ff8800' }],
};

describe('TrackRow tag cell', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(
      http.get('http://localhost/tags', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
  });

  it('renders existing tag pills (desktop)', () => {
    render(
      <W>
        <TrackRow track={baseTrack} variant="desktop" categoryId="c1" />
      </W>,
    );
    expect(screen.getByText('Vocal')).toBeInTheDocument();
  });
});

describe('TrackRow — used_in_playlist badge', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(
      http.get('http://localhost/tags', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
  });

  it('renders badge when used_in_playlist=true (desktop)', () => {
    const track: CategoryTrack = { ...baseTrack, used_in_playlist: true };
    render(
      <W>
        <TrackRow track={track} variant="desktop" categoryId="c1" />
      </W>,
    );
    expect(screen.getByText('In playlist')).toBeInTheDocument();
  });

  it('does not render badge when used_in_playlist=false (desktop)', () => {
    const track: CategoryTrack = { ...baseTrack, used_in_playlist: false };
    render(
      <W>
        <TrackRow track={track} variant="desktop" categoryId="c1" />
      </W>,
    );
    expect(screen.queryByText('In playlist')).not.toBeInTheDocument();
  });

  it('renders badge when used_in_playlist=true (mobile)', () => {
    const track: CategoryTrack = { ...baseTrack, used_in_playlist: true };
    render(
      <WMobile>
        <TrackRow track={track} variant="mobile" categoryId="c1" />
      </WMobile>,
    );
    expect(screen.getByText('In playlist')).toBeInTheDocument();
  });

  it('does not render badge when used_in_playlist=false (mobile)', () => {
    const track: CategoryTrack = { ...baseTrack, used_in_playlist: false };
    render(
      <WMobile>
        <TrackRow track={track} variant="mobile" categoryId="c1" />
      </WMobile>,
    );
    expect(screen.queryByText('In playlist')).not.toBeInTheDocument();
  });
});

describe('TrackRow — Play button', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(http.get('http://localhost/tags', () => HttpResponse.json([])));
  });

  it('does NOT render a play icon when onPlay is omitted', () => {
    render(
      <W>
        <TrackRow track={baseTrack} variant="desktop" categoryId="c1" />
      </W>,
    );
    expect(screen.queryByRole('button', { name: /play track/i })).not.toBeInTheDocument();
  });

  it('renders enabled play button when onPlay provided and spotify_id present', async () => {
    const onPlay = vi.fn();
    const user = userEvent.setup();
    render(
      <W>
        <TrackRow
          track={{ ...baseTrack, spotify_id: 'sp1' }}
          variant="desktop"
          categoryId="c1"
          onPlay={onPlay}
        />
      </W>,
    );
    const btn = screen.getByRole('button', { name: /play track/i });
    expect(btn).toBeEnabled();
    await user.click(btn);
    expect(onPlay).toHaveBeenCalledOnce();
  });

  it('disables play button when spotify_id is null', () => {
    const onPlay = vi.fn();
    render(
      <W>
        <TrackRow
          track={{ ...baseTrack, spotify_id: null }}
          variant="desktop"
          categoryId="c1"
          onPlay={onPlay}
        />
      </W>,
    );
    expect(screen.getByRole('button', { name: /play track/i })).toBeDisabled();
  });
});
