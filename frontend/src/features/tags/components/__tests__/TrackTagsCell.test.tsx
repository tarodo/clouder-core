import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { TrackTagsCell } from '../TrackTagsCell';

function W({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  return (
    <MantineProvider theme={testTheme}>
      <Notifications />
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </MantineProvider>
  );
}

describe('TrackTagsCell', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(
      http.get('http://localhost/tags', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
  });

  it('renders pills for current tags', () => {
    render(
      <W>
        <TrackTagsCell
          categoryId="c1"
          trackId="t1"
          tags={[
            { id: 'tg1', name: 'Vocal', color: '#ff8800' },
            { id: 'tg2', name: 'Dark', color: null },
          ]}
        />
      </W>,
    );
    expect(screen.getByText('Vocal')).toBeInTheDocument();
    expect(screen.getByText('Dark')).toBeInTheDocument();
  });

  it('opens the popover on "+" click', async () => {
    render(
      <W>
        <TrackTagsCell categoryId="c1" trackId="t1" tags={[]} />
      </W>,
    );
    await userEvent.click(screen.getByRole('button', { name: /add tag/i }));
    expect(await screen.findByPlaceholderText(/search.*create/i)).toBeInTheDocument();
  });

  it('opens the popover on pill click', async () => {
    render(
      <W>
        <TrackTagsCell
          categoryId="c1"
          trackId="t1"
          tags={[{ id: 'tg1', name: 'Vocal', color: '#ff8800' }]}
        />
      </W>,
    );
    await userEvent.click(screen.getByText('Vocal'));
    expect(await screen.findByPlaceholderText(/search.*create/i)).toBeInTheDocument();
  });
});
