import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../test/theme';
import { DeviceRow } from '../DeviceRow';
import type { SpotifyDevice } from '../lib/deviceTypes';

const wrap = (children: React.ReactNode) => (
  <MantineProvider theme={testTheme}>{children}</MantineProvider>
);

const dev = (over: Partial<SpotifyDevice> = {}): SpotifyDevice => ({
  id: 'd1',
  name: 'Device',
  type: 'Computer',
  is_active: false,
  is_private_session: false,
  is_restricted: false,
  volume_percent: null,
  ...over,
});

describe('DeviceRow', () => {
  it('renders icon, name, calls onPick on click', async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    render(wrap(<DeviceRow device={dev({ name: 'Laptop' })} cloderTabId={null} isActive={false} onPick={onPick} />));
    expect(screen.getByText('Laptop')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Laptop/ }));
    expect(onPick).toHaveBeenCalledWith('d1');
  });

  it('renders active check when isActive=true', () => {
    render(wrap(<DeviceRow device={dev()} cloderTabId={null} isActive={true} onPick={() => {}} />));
    expect(screen.getByLabelText(/active/i)).toBeInTheDocument();
  });

  it('renders restricted badge when device.is_restricted=true', () => {
    render(wrap(<DeviceRow device={dev({ is_restricted: true })} cloderTabId={null} isActive={false} onPick={() => {}} />));
    expect(screen.getByText(/restricted/i)).toBeInTheDocument();
  });
});
