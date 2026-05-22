import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { TrackTagsCell } from '../TrackTagsCell';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

describe('TrackTagsCell', () => {
  it('renders pills for current tags', () => {
    r(
      <TrackTagsCell
        tags={[
          { id: 'tg1', name: 'Vocal', color: '#ff8800' },
          { id: 'tg2', name: 'Dark', color: null },
        ]}
      />,
    );
    expect(screen.getByText('Vocal')).toBeInTheDocument();
    expect(screen.getByText('Dark')).toBeInTheDocument();
  });

  it('renders no add button (read-only)', () => {
    r(<TrackTagsCell tags={[]} />);
    expect(screen.queryByRole('button', { name: /add tag/i })).toBeNull();
  });
});
