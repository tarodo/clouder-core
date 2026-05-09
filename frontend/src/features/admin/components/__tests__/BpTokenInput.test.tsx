import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { BpTokenInput } from '../BpTokenInput';
import { bpTokenStore } from '../../lib/bpTokenStore';

function ui() {
  return (
    <MantineProvider theme={testTheme}>
      <BpTokenInput />
    </MantineProvider>
  );
}

describe('BpTokenInput', () => {
  it('captures input into store and switches to loaded state', async () => {
    bpTokenStore.clear();
    render(ui());
    // fireEvent.change sets the full value in one event — avoids mid-type re-renders
    // that would unmount the input before all characters are recorded.
    fireEvent.change(screen.getByTestId('bp-token-input'), { target: { value: 'abc' } });
    expect(bpTokenStore.get()).toBe('abc');
    expect(screen.getByText('Beatport token loaded')).toBeInTheDocument();
  });

  it('reset clears the store and re-shows the input', async () => {
    bpTokenStore.set('abc');
    render(ui());
    await userEvent.click(screen.getByText('Reset'));
    expect(bpTokenStore.get()).toBeNull();
    expect(screen.getByTestId('bp-token-input')).toBeInTheDocument();
  });
});
