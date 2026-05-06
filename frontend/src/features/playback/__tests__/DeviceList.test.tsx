import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../test/theme';
import { DeviceList } from '../DeviceList';
import type { SpotifyDevice } from '../lib/deviceTypes';

const wrap = (children: React.ReactNode) => (
  <MantineProvider theme={testTheme}>{children}</MantineProvider>
);

const baseProps = {
  devices: [] as readonly SpotifyDevice[],
  active: null as SpotifyDevice | null,
  cloderTabId: null as string | null,
  isLoading: false,
  error: null as 'network' | 'auth' | null,
  sdkReady: true,
  onPick: vi.fn(),
  onRefresh: vi.fn(),
};

describe('DeviceList', () => {
  it('renders connecting skeleton when sdkReady=false', () => {
    render(wrap(<DeviceList {...baseProps} sdkReady={false} />));
    expect(screen.getByText(/Connecting/i)).toBeInTheDocument();
  });

  it('renders loading skeleton when isLoading + empty list', () => {
    render(wrap(<DeviceList {...baseProps} isLoading={true} />));
    expect(screen.getByTestId('device-list-loading')).toBeInTheDocument();
  });

  it('renders empty state when ready, not loading, list empty, no error', () => {
    render(wrap(<DeviceList {...baseProps} />));
    expect(screen.getByText(/No devices found/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Refresh/i })).toBeInTheDocument();
  });

  it('renders network error with retry', async () => {
    const onRefresh = vi.fn();
    const user = userEvent.setup();
    render(wrap(<DeviceList {...baseProps} error="network" onRefresh={onRefresh} />));
    await user.click(screen.getByRole('button', { name: /Retry/i }));
    expect(onRefresh).toHaveBeenCalled();
  });

  it('renders auth error', () => {
    render(wrap(<DeviceList {...baseProps} error="auth" />));
    expect(screen.getByText(/Re-sign in/i)).toBeInTheDocument();
  });

  it('renders rows when list non-empty', () => {
    const devices: SpotifyDevice[] = [
      { id: 'd1', name: 'Laptop', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'd2', name: 'Phone', type: 'Smartphone', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    render(wrap(<DeviceList {...baseProps} devices={devices} active={devices[0]!} />));
    expect(screen.getByRole('button', { name: 'Laptop' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Phone' })).toBeInTheDocument();
  });
});
