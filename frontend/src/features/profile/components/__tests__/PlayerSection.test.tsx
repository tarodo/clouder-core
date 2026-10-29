import { afterEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { PlayerSection } from '../PlayerSection';

const KEY = 'clouder.player_scrubber';

function renderSection() {
  render(
    <MantineProvider theme={testTheme}>
      <PlayerSection />
    </MantineProvider>,
  );
}

describe('PlayerSection', () => {
  afterEach(() => window.localStorage.removeItem(KEY));

  it('defaults to the waveform', () => {
    renderSection();
    expect(screen.getByRole('radio', { name: 'Waveform' })).toBeChecked();
  });

  it('keeps the choice on this device', async () => {
    renderSection();
    await userEvent.click(screen.getByText('Progress bar'));
    expect(screen.getByRole('radio', { name: 'Progress bar' })).toBeChecked();
    expect(JSON.parse(window.localStorage.getItem(KEY) ?? 'null')).toBe('progress');
  });
});
