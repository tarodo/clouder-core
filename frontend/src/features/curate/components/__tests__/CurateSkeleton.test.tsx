import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { CurateSkeleton } from '../CurateSkeleton';

describe('CurateSkeleton', () => {
  it('renders the loading layout', () => {
    render(
      <MantineProvider theme={testTheme}>
        <CurateSkeleton />
      </MantineProvider>,
    );
    expect(screen.getByTestId('curate-skeleton')).toBeInTheDocument();
  });
});
