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
      { id: 'tg-a', name: 'acid', color: '#f00' },
      { id: 'tg-b', name: 'banger', color: '#0f0' },
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
});
