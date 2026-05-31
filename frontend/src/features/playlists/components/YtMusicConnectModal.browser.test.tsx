/**
 * Browser-mode smoke for YtMusicConnectModal: verifies the user code is rendered
 * in a real browser engine after the device-code API is mocked.
 */
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import '../../../i18n';
import { YtMusicConnectModal } from './YtMusicConnectModal';

vi.mock('../../../api/client', () => ({
  api: vi.fn(async () => ({
    device_code: 'dc',
    user_code: 'ABCD-EFGH',
    verification_url: 'https://www.google.com/device',
    interval: 60,
    expires_in: 1800,
  })),
}));

describe('YtMusicConnectModal — browser smoke', () => {
  it('shows the user code and open link after device-code resolves', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MantineProvider defaultColorScheme="light">
          <YtMusicConnectModal opened onClose={() => {}} onConnected={() => {}} />
        </MantineProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByText('ABCD-EFGH')).toBeVisible();
    expect(screen.getByRole('link', { name: /open google\.com\/device/i })).toHaveAttribute(
      'href',
      'https://www.google.com/device',
    );
  });
});
