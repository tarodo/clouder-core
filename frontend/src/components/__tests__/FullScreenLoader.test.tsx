import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { FullScreenLoader } from '../FullScreenLoader';

describe('FullScreenLoader', () => {
  it('shows a gray pulsing bar with the copy, no spinner', () => {
    render(
      <MantineProvider>
        <FullScreenLoader copy="Signing in…" />
      </MantineProvider>,
    );
    expect(screen.getByTestId('fullscreen-skeleton')).toBeDefined();
    expect(screen.getByText('Signing in…')).toBeDefined();
    expect(document.querySelector('.mantine-Loader-root')).toBeNull();
  });
});
