import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { MemoryRouter, useSearchParams } from 'react-router';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { TracksTab, type TracksTabProps } from '../TracksTab';
import type { CategoryTrack } from '../../hooks/useCategoryTracks';

function makeQc() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

function Wrapper({
  children,
  initialUrl = '/categories/c1',
}: {
  children: React.ReactNode;
  initialUrl?: string;
}) {
  return (
    <MantineProvider theme={testTheme}>
      <ModalsProvider>
        <Notifications />
        <QueryClientProvider client={makeQc()}>
          <MemoryRouter initialEntries={[initialUrl]}>{children}</MemoryRouter>
        </QueryClientProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

function mkTrack(i: number): CategoryTrack {
  return {
    id: `t${i}`,
    title: `Track ${i}`,
    mix_name: null,
    artists: [{ id: 'a1', name: 'Artist' }],
    label: { id: 'l1', name: 'Cool Label' },
    bpm: 120,
    length_ms: 360000,
    publish_date: '2026-01-01',
    spotify_release_date: '2026-01-03',
    isrc: null,
    spotify_id: null,
    release_type: null,
    is_ai_suspected: false,
    used_in_playlist: false,
    added_at: '2026-01-01T00:00:00Z',
    source_triage_block_id: null,
    tags: [],
  };
}

function mkTracks(start: number, count: number): CategoryTrack[] {
  return Array.from({ length: count }, (_, i) => mkTrack(start + i));
}

type Overrides = Partial<TracksTabProps>;

function mkProps(overrides: Overrides = {}): TracksTabProps {
  return {
    categoryId: 'c1',
    styleId: 's1',
    items: [],
    total: 0,
    isLoading: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
    rawSearch: '',
    setRawSearch: vi.fn(),
    debounced: '',
    sortKey: 'added_at',
    sortDir: 'desc',
    setSortKey: vi.fn(),
    setSortDir: vi.fn(),
    onPlay: vi.fn(),
    ...overrides,
  };
}

describe('TracksTab', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    // The tag-filter bar fetches tags via msw; keep it happy.
    server.use(http.get('http://localhost/tags', () => HttpResponse.json([])));
  });

  it('renders track rows and a Show-more button when hasNextPage', async () => {
    const fetchNextPage = vi.fn();
    render(
      <Wrapper initialUrl="/categories/c1?fresh=0">
        <TracksTab
          {...mkProps({
            items: mkTracks(0, 50),
            total: 60,
            hasNextPage: true,
            fetchNextPage,
          })}
        />
      </Wrapper>,
    );
    expect(await screen.findByText('Track 0')).toBeInTheDocument();
    expect(screen.getByText(/Show more \(10 remaining\)/i)).toBeInTheDocument();
    await userEvent.click(screen.getByText(/Show more/i));
    expect(fetchNextPage).toHaveBeenCalledOnce();
  });

  it('shows empty-search state when debounced is set and items are empty', async () => {
    render(
      <Wrapper initialUrl="/categories/c1?fresh=0">
        <TracksTab
          {...mkProps({
            items: [],
            total: 0,
            debounced: 'zzz',
            rawSearch: 'zzz',
          })}
        />
      </Wrapper>,
    );
    expect(await screen.findByText(/no tracks match 'zzz'/i)).toBeInTheDocument();
  });

  it('shows no-tracks empty state when fresh=0 and items empty', async () => {
    render(
      <Wrapper initialUrl="/categories/c1?fresh=0">
        <TracksTab {...mkProps({ items: [], total: 0 })} />
      </Wrapper>,
    );
    expect(await screen.findByText(/no tracks yet/i)).toBeInTheDocument();
  });

  it('shows no-fresh-tracks empty state by default and disables fresh on click', async () => {
    function Probe() {
      const [params] = useSearchParams();
      return <span data-testid="fresh-param">{params.get('fresh') ?? 'absent'}</span>;
    }
    render(
      <Wrapper initialUrl="/categories/c1">
        <TracksTab {...mkProps({ items: [], total: 0 })} />
        <Probe />
      </Wrapper>,
    );
    expect(screen.getByTestId('fresh-param')).toHaveTextContent('absent');
    expect(await screen.findByText(/no fresh tracks/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /show all tracks/i }));
    await waitFor(() => expect(screen.getByTestId('fresh-param')).toHaveTextContent('0'));
  });

  it('renders Title and Added sortable headers with the active sort marked', async () => {
    render(
      <Wrapper initialUrl="/categories/c1?fresh=0">
        <TracksTab
          {...mkProps({
            items: mkTracks(0, 1),
            total: 1,
          })}
        />
      </Wrapper>,
    );
    expect(await screen.findByText('Track 0')).toBeInTheDocument();
    expect(
      screen.getByRole('columnheader', { name: /Added/i }),
    ).toHaveAttribute('aria-sort', 'descending');
    expect(
      screen.getByRole('columnheader', { name: /Title/i }),
    ).toHaveAttribute('aria-sort', 'none');
  });

  it('clicking Title swaps sort to title via setSortKey/setSortDir', async () => {
    const setSortKey = vi.fn();
    const setSortDir = vi.fn();
    render(
      <Wrapper initialUrl="/categories/c1?fresh=0">
        <TracksTab
          {...mkProps({
            items: mkTracks(0, 1),
            total: 1,
            setSortKey,
            setSortDir,
          })}
        />
      </Wrapper>,
    );
    await userEvent.click(
      await screen.findByRole('button', { name: /Title/i }),
    );
    expect(setSortKey).toHaveBeenCalledWith('title');
    expect(setSortDir).toHaveBeenCalledWith('asc');
  });

  it('clicking the same sort header toggles direction', async () => {
    const setSortDir = vi.fn();
    const setSortKey = vi.fn();
    render(
      <Wrapper initialUrl="/categories/c1?fresh=0">
        <TracksTab
          {...mkProps({
            items: mkTracks(0, 1),
            total: 1,
            sortKey: 'added_at',
            sortDir: 'desc',
            setSortDir,
            setSortKey,
          })}
        />
      </Wrapper>,
    );
    await userEvent.click(
      await screen.findByRole('button', { name: /Added/i }),
    );
    expect(setSortKey).not.toHaveBeenCalled();
    expect(setSortDir).toHaveBeenCalledTimes(1);
    const updater = setSortDir.mock.calls[0]?.[0];
    expect(typeof updater).toBe('function');
    expect((updater as (d: 'asc' | 'desc') => 'asc' | 'desc')('desc')).toBe('asc');
  });

  it('renders a kebab trigger per desktop row', async () => {
    render(
      <Wrapper initialUrl="/categories/c1?fresh=0">
        <TracksTab
          {...mkProps({
            items: mkTracks(0, 3),
            total: 3,
          })}
        />
      </Wrapper>,
    );
    await screen.findByText('Track 0');
    const triggers = screen.getAllByRole('button', { name: /track actions/i });
    expect(triggers).toHaveLength(3);
  });

  it('opens the manage-tags modal when the button is clicked', async () => {
    render(
      <Wrapper initialUrl="/categories/c1?fresh=0">
        <TracksTab {...mkProps({ items: mkTracks(0, 1), total: 1 })} />
      </Wrapper>,
    );
    await userEvent.click(
      await screen.findByRole('button', { name: /manage tags/i }),
    );
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });
});
