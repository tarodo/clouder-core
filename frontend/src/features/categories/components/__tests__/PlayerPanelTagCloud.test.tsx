import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';

// Mock the tags barrel: real-ish useTags + a stub TrackTagsPopover that renders
// its target and a marker input when opened (so we can assert the "+" opens it
// without pulling React Query / the popover's own mutations).
vi.mock('../../../tags', () => ({
  useTags: () => ({
    data: [
      { id: 'tg-a', name: 'acid', color: '#ff0000' },
      { id: 'tg-b', name: 'banger', color: '#00ff00' },
    ],
    isLoading: false,
  }),
  TrackTagsPopover: ({
    opened,
    target,
  }: {
    opened: boolean;
    target: React.ReactNode;
  }) => (
    <div data-testid="tags-popover">
      {target}
      {opened && <input placeholder="search or create" />}
    </div>
  ),
}));

import { PlayerPanelTagCloud } from '../PlayerPanelTagCloud';

function ui(props: Parameters<typeof PlayerPanelTagCloud>[0]) {
  return (
    <MantineProvider>
      <PlayerPanelTagCloud {...props} />
    </MantineProvider>
  );
}

const base = { categoryId: 'c1', trackId: 't-1', onAdd: vi.fn(), onRemove: vi.fn() };

describe('PlayerPanelTagCloud', () => {
  it('renders all user tags', () => {
    render(ui({ ...base, assignedTagIds: [] }));
    expect(screen.getByText('acid')).toBeInTheDocument();
    expect(screen.getByText('banger')).toBeInTheDocument();
  });

  it('marks assigned tags as checked', () => {
    render(ui({ ...base, assignedTagIds: ['tg-a'] }));
    const acidInput = screen
      .getByText('acid')
      .closest('.mantine-Chip-root')!
      .querySelector('input')! as HTMLInputElement;
    expect(acidInput.checked).toBe(true);
  });

  it('click on unassigned chip calls onAdd', async () => {
    const onAdd = vi.fn();
    render(ui({ ...base, assignedTagIds: [], onAdd }));
    await userEvent.click(screen.getByText('acid'));
    expect(onAdd).toHaveBeenCalledWith('tg-a');
  });

  it('click on assigned chip calls onRemove', async () => {
    const onRemove = vi.fn();
    render(ui({ ...base, assignedTagIds: ['tg-a'], onRemove }));
    await userEvent.click(screen.getByText('acid'));
    expect(onRemove).toHaveBeenCalledWith('tg-a');
  });

  it('renders an add button that opens the tag popover', async () => {
    render(ui({ ...base, assignedTagIds: [] }));
    const add = screen.getByRole('button', { name: /add tag/i });
    expect(add).toBeInTheDocument();
    await userEvent.click(add);
    expect(screen.getByPlaceholderText(/search or create/i)).toBeInTheDocument();
  });

  it('hides the checkmark on assigned chips (color conveys selection)', () => {
    render(ui({ ...base, assignedTagIds: ['tg-a'] }));
    const acidChip = screen.getByText('acid').closest('.mantine-Chip-root')! as HTMLElement;
    const iconWrapper = acidChip.querySelector('.mantine-Chip-iconWrapper') as HTMLElement | null;
    expect(iconWrapper).not.toBeNull();
    expect(iconWrapper!.style.display).toBe('none');
  });

  it('assigned chip shows a soft tint, unassigned chip is transparent', () => {
    render(ui({ ...base, assignedTagIds: ['tg-a'] }));
    const acidLabel = screen
      .getByText('acid')
      .closest('.mantine-Chip-root')!
      .querySelector('.mantine-Chip-label')! as HTMLElement;
    const bangerLabel = screen
      .getByText('banger')
      .closest('.mantine-Chip-root')!
      .querySelector('.mantine-Chip-label')! as HTMLElement;
    expect(acidLabel.style.backgroundColor).toBe('rgba(255, 0, 0, 0.13)');
    expect(bangerLabel.style.backgroundColor).toBe('transparent');
  });

  it('both selected and unselected chip labels carry pinned padding', () => {
    render(ui({ ...base, assignedTagIds: ['tg-a'] }));
    const acidLabel = screen
      .getByText('acid')
      .closest('.mantine-Chip-root')!
      .querySelector('.mantine-Chip-label')! as HTMLElement;
    const bangerLabel = screen
      .getByText('banger')
      .closest('.mantine-Chip-root')!
      .querySelector('.mantine-Chip-label')! as HTMLElement;
    // selected and unselected chips carry the SAME pinned inline padding
    expect(acidLabel.style.paddingLeft).toBe('var(--chip-padding)');
    expect(acidLabel.style.paddingRight).toBe('var(--chip-padding)');
    expect(bangerLabel.style.paddingLeft).toBe('var(--chip-padding)');
    expect(bangerLabel.style.paddingRight).toBe('var(--chip-padding)');
  });
});
