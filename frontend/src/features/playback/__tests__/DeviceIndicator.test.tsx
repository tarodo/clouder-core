import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../test/theme';
import { DeviceIndicator } from '../DeviceIndicator';
import type { SpotifyDevice } from '../lib/deviceTypes';

const wrap = (children: React.ReactNode) => (
  <MantineProvider theme={testTheme}>{children}</MantineProvider>
);

const dev: SpotifyDevice = {
  id: 'd1',
  name: 'KitchenSpeaker',
  type: 'Speaker',
  is_active: true,
  is_private_session: false,
  is_restricted: false,
  volume_percent: 60,
};

describe('DeviceIndicator', () => {
  it('renders icon and name in full mode', () => {
    render(wrap(<DeviceIndicator mode="full" active={dev} cloderTabId={null} onOpen={() => {}} />));
    expect(screen.getByText('KitchenSpeaker')).toBeInTheDocument();
  });

  it('renders compact mode without chevron', () => {
    render(wrap(<DeviceIndicator mode="compact" active={dev} cloderTabId={null} onOpen={() => {}} />));
    expect(screen.queryByLabelText(/chevron/i)).toBeNull();
  });

  it('calls onOpen with the button element when clicked', async () => {
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(wrap(<DeviceIndicator mode="full" active={dev} cloderTabId={null} onOpen={onOpen} />));
    await user.click(screen.getByRole('button'));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0]![0]).toBeInstanceOf(HTMLElement);
  });

  it('shows "No device" when active is null', () => {
    render(wrap(<DeviceIndicator mode="full" active={null} cloderTabId={null} onOpen={() => {}} />));
    expect(screen.getByText(/No device/i)).toBeInTheDocument();
  });
});
