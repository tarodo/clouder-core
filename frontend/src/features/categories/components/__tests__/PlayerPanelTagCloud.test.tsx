import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { PlayerPanelTagCloud } from '../PlayerPanelTagCloud';

vi.mock('../../../tags', () => ({
  useTags: () => ({
    data: [
      { id: 'tg-a', name: 'acid', color: '#f00' },
      { id: 'tg-b', name: 'banger', color: '#0f0' },
    ],
    isLoading: false,
  }),
}));

function ui(props: Parameters<typeof PlayerPanelTagCloud>[0]) {
  return (
    <MantineProvider>
      <PlayerPanelTagCloud {...props} />
    </MantineProvider>
  );
}

describe('PlayerPanelTagCloud', () => {
  it('renders all user tags', () => {
    render(ui({ trackId: 't-1', assignedTagIds: [], onAdd: vi.fn(), onRemove: vi.fn() }));
    expect(screen.getByText('acid')).toBeInTheDocument();
    expect(screen.getByText('banger')).toBeInTheDocument();
  });

  it('marks assigned tags as checked', () => {
    render(ui({ trackId: 't-1', assignedTagIds: ['tg-a'], onAdd: vi.fn(), onRemove: vi.fn() }));
    const acidRoot = screen.getByText('acid').closest('.mantine-Chip-root')!;
    const acidInput = acidRoot.querySelector('input')! as HTMLInputElement;
    expect(acidInput.checked).toBe(true);
    const bangerRoot = screen.getByText('banger').closest('.mantine-Chip-root')!;
    const bangerInput = bangerRoot.querySelector('input')! as HTMLInputElement;
    expect(bangerInput.checked).toBe(false);
  });

  it('click on unassigned chip calls onAdd', async () => {
    const onAdd = vi.fn();
    render(ui({ trackId: 't-1', assignedTagIds: [], onAdd, onRemove: vi.fn() }));
    await userEvent.click(screen.getByText('acid'));
    expect(onAdd).toHaveBeenCalledWith('tg-a');
  });

  it('click on assigned chip calls onRemove', async () => {
    const onRemove = vi.fn();
    render(ui({ trackId: 't-1', assignedTagIds: ['tg-a'], onAdd: vi.fn(), onRemove }));
    await userEvent.click(screen.getByText('acid'));
    expect(onRemove).toHaveBeenCalledWith('tg-a');
  });
});
