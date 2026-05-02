import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import { DndContext } from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CategoryRow } from '../CategoryRow';

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <MantineProvider>
      <MemoryRouter>
        <DndContext>
          <SortableContext items={['c1']} strategy={verticalListSortingStrategy}>
            {children}
          </SortableContext>
        </DndContext>
      </MemoryRouter>
    </MantineProvider>
  );
}

const cat = {
  id: 'c1',
  style_id: 's1',
  style_name: 'House',
  name: 'Deep',
  position: 0,
  track_count: 12,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

describe('CategoryRow', () => {
  it('renders name and track count', () => {
    render(
      <Wrapper>
        <CategoryRow category={cat} onRename={() => {}} onDelete={() => {}} />
      </Wrapper>,
    );
    expect(screen.getByText('Deep')).toBeInTheDocument();
    expect(screen.getByText('12 tracks')).toBeInTheDocument();
  });

  it('exposes drag handle with aria-roledescription', () => {
    render(
      <Wrapper>
        <CategoryRow category={cat} onRename={() => {}} onDelete={() => {}} />
      </Wrapper>,
    );
    const handle = screen.getByRole('button', { name: /drag/i });
    expect(handle).toHaveAttribute('aria-roledescription', 'sortable');
  });

  it('fires onRename when kebab → Rename clicked', async () => {
    const onRename = vi.fn();
    render(
      <Wrapper>
        <CategoryRow category={cat} onRename={onRename} onDelete={() => {}} />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /actions/i }));
    await userEvent.click(screen.getByText('Rename'));
    expect(onRename).toHaveBeenCalledWith(cat);
  });
});
