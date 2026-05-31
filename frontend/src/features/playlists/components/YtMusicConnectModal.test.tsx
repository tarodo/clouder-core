import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderApp } from '../../../test/renderApp';
import { YtMusicConnectModal } from './YtMusicConnectModal';
import * as client from '../../../api/client';

describe('YtMusicConnectModal', () => {
  it('shows the user code and verification link', async () => {
    vi.spyOn(client, 'api').mockResolvedValue({
      device_code: 'dc', user_code: 'ABCD-EFGH',
      verification_url: 'https://www.google.com/device',
      interval: 1, expires_in: 1800,
    });
    renderApp({
      initialEntries: ['/'],
      children: (
        <YtMusicConnectModal opened onClose={() => {}} onConnected={() => {}} />
      ),
    });
    expect(await screen.findByText('ABCD-EFGH')).toBeInTheDocument();
  });
});
