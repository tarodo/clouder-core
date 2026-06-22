import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { PlayerPanelPlaylistCloud } from '../PlayerPanelPlaylistCloud';

const mockPlaylists = Array.from({ length: 12 }, (_, i) => ({
  id: `pl-${i}`,
  name: `Playlist ${i}`,
  status: 'active' as const,
  track_count: i,
}));

vi.mock('../../../playlists/hooks/usePlaylists', () => ({
  usePlaylists: () => ({
    data: { items: mockPlaylists, total: 12, limit: 100, offset: 0 },
    isLoading: false,
  }),
}));

function ui(props: Parameters<typeof PlayerPanelPlaylistCloud>[0]) {
  return (
    <MantineProvider>
      <PlayerPanelPlaylistCloud {...props} />
    </MantineProvider>
  );
}

describe('PlayerPanelPlaylistCloud', () => {
  it('renders hotkey badges 1-9 then 0 on first 10', () => {
    render(ui({ trackId: 't-1', trackPlaylistIds: [], onAdd: vi.fn(), onRemove: vi.fn() }));
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('9')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.queryByText('11')).not.toBeInTheDocument();
  });

  it('marks the selected playlist button as filled', () => {
    render(
      ui({ trackId: 't-1', trackPlaylistIds: ['pl-2'], onAdd: vi.fn(), onRemove: vi.fn() }),
    );
    const btn = screen.getByText('Playlist 2 (2)').closest('button')!;
    expect(btn).toHaveAttribute('data-variant', 'filled');
  });

  it('renders an unselected playlist button as default variant', () => {
    render(ui({ trackId: 't-1', trackPlaylistIds: [], onAdd: vi.fn(), onRemove: vi.fn() }));
    const btn = screen.getByText('Playlist 0 (0)').closest('button')!;
    expect(btn).toHaveAttribute('data-variant', 'default');
  });

  it('click on a default button calls onAdd', async () => {
    const onAdd = vi.fn();
    render(ui({ trackId: 't-1', trackPlaylistIds: [], onAdd, onRemove: vi.fn() }));
    await userEvent.click(screen.getByText('Playlist 0 (0)'));
    expect(onAdd).toHaveBeenCalledWith('pl-0');
  });

  it('click on a filled button calls onRemove', async () => {
    const onRemove = vi.fn();
    render(ui({ trackId: 't-1', trackPlaylistIds: ['pl-0'], onAdd: vi.fn(), onRemove }));
    await userEvent.click(screen.getByText('Playlist 0 (0)'));
    expect(onRemove).toHaveBeenCalledWith('pl-0');
  });
});
