import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../test/theme';
import { AiBadge } from '../AiBadge';

describe('AiBadge', () => {
  it.each([
    ['high', 'red'],
    ['medium', 'orange'],
    ['low', 'yellow'],
  ] as const)('%s reads "AI" in %s', (level, color) => {
    render(
      <MantineProvider theme={testTheme}>
        <AiBadge verdict={level} />
      </MantineProvider>,
    );
    const badge = screen.getByText('AI').closest('[data-level]');
    expect(badge).toHaveAttribute('data-level', level);
    expect(badge?.getAttribute('style')).toContain(`--mantine-color-${color}-light`);
  });
});
