import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { MemoryRouter } from 'react-router';
import { testTheme } from '../../../test/theme';
import { DeviceIndicator } from '../DeviceIndicator';
import { PlaybackProvider } from '../PlaybackProvider';
import { AuthProvider } from '../../../auth/AuthProvider';
import { spotifyTokenStore } from '../../../auth/spotifyTokenStore';
import type { SpotifyDevice } from '../lib/deviceTypes';

const wrap = (children: React.ReactNode) => (
  <MantineProvider theme={testTheme}>
    <Notifications />
    <MemoryRouter>
      <AuthProvider>
        <PlaybackProvider>{children}</PlaybackProvider>
      </AuthProvider>
    </MemoryRouter>
  </MantineProvider>
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

beforeEach(() => {
  spotifyTokenStore.set('tok');
  // Force MOBILE breakpoint so DeviceIndicator renders the bare button
  // (no Popover) — popover anchoring is now exercised by the
  // DevicePickerSurface integration test on desktop instead.
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn((q: string) => ({
      matches: q.includes('max-width'),
      media: q,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

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
