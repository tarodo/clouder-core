import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { YearNavigator } from '../YearNavigator';

function ui(props: React.ComponentProps<typeof YearNavigator>) {
  return (
    <MantineProvider theme={testTheme}>
      <YearNavigator {...props} />
    </MantineProvider>
  );
}

describe('YearNavigator', () => {
  it('decrements via prev button', async () => {
    const onChange = vi.fn();
    render(ui({ year: 2026, onChange }));
    await userEvent.click(screen.getByLabelText('Previous year'));
    expect(onChange).toHaveBeenCalledWith(2025);
  });

  it('increments via next button', async () => {
    const onChange = vi.fn();
    render(ui({ year: 2026, onChange }));
    await userEvent.click(screen.getByLabelText('Next year'));
    expect(onChange).toHaveBeenCalledWith(2027);
  });

  it('disables prev at min', () => {
    render(ui({ year: 2024, onChange: vi.fn() }));
    expect(screen.getByLabelText('Previous year')).toBeDisabled();
  });
});
