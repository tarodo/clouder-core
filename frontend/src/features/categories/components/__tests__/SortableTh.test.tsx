import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider, Table } from '@mantine/core';
import { SortableTh } from '../SortableTh';

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <MantineProvider>
      <Table>
        <Table.Thead>
          <Table.Tr>{children}</Table.Tr>
        </Table.Thead>
      </Table>
    </MantineProvider>
  );
}

describe('SortableTh', () => {
  it('renders children', () => {
    render(
      <Wrapper>
        <SortableTh active={false} dir="asc" onClick={() => {}}>
          Title
        </SortableTh>
      </Wrapper>,
    );
    expect(screen.getByText('Title')).toBeInTheDocument();
  });

  it('sets aria-sort=none when inactive', () => {
    render(
      <Wrapper>
        <SortableTh active={false} dir="asc" onClick={() => {}}>
          Title
        </SortableTh>
      </Wrapper>,
    );
    expect(
      screen.getByRole('columnheader', { name: /Title/ }),
    ).toHaveAttribute('aria-sort', 'none');
  });

  it('sets aria-sort=ascending when active asc', () => {
    render(
      <Wrapper>
        <SortableTh active dir="asc" onClick={() => {}}>
          Title
        </SortableTh>
      </Wrapper>,
    );
    expect(
      screen.getByRole('columnheader', { name: /Title/ }),
    ).toHaveAttribute('aria-sort', 'ascending');
  });

  it('sets aria-sort=descending when active desc', () => {
    render(
      <Wrapper>
        <SortableTh active dir="desc" onClick={() => {}}>
          Title
        </SortableTh>
      </Wrapper>,
    );
    expect(
      screen.getByRole('columnheader', { name: /Title/ }),
    ).toHaveAttribute('aria-sort', 'descending');
  });

  it('fires onClick when activated', async () => {
    const onClick = vi.fn();
    render(
      <Wrapper>
        <SortableTh active={false} dir="asc" onClick={onClick}>
          Title
        </SortableTh>
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /Title/ }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
