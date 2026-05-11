import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { TagsManagerModal } from '../TagsManagerModal';

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

function W({ children }: { children: React.ReactNode }) {
  const qc = makeClient();
  return (
    <MantineProvider theme={testTheme}>
      <ModalsProvider>
        <Notifications />
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

describe('TagsManagerModal', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(
      http.get('http://localhost/tags', () =>
        HttpResponse.json({
          items: [
            { id: 'tg1', name: 'Vocal', color: '#ff8800',
              created_at: 'x', updated_at: 'x' },
            { id: 'tg2', name: 'Dark', color: null,
              created_at: 'x', updated_at: 'x' },
          ],
          total: 2, limit: 200, offset: 0,
        }),
      ),
    );
  });

  it('lists existing tags', async () => {
    render(
      <W>
        <TagsManagerModal opened onClose={() => {}} />
      </W>,
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Vocal')).toBeInTheDocument();
    expect(within(dialog).getByText('Dark')).toBeInTheDocument();
  });

  it('creates a tag from the inline form', async () => {
    let captured: unknown = null;
    server.use(
      http.post('http://localhost/tags', async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json(
          { id: 'tg-new', name: 'Drum', color: null,
            created_at: 'x', updated_at: 'x' },
          { status: 201 },
        );
      }),
    );
    render(
      <W>
        <TagsManagerModal opened onClose={() => {}} />
      </W>,
    );
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: /new tag/i }));
    await userEvent.type(within(dialog).getByRole('textbox', { name: /name/i }), 'Drum');
    await userEvent.click(within(dialog).getByRole('button', { name: /^create$/i }));
    expect(captured).toEqual({ name: 'Drum', color: null });
  });

  it('shows the 409 conflict message inline on duplicate name', async () => {
    server.use(
      http.post('http://localhost/tags', () =>
        HttpResponse.json(
          { error_code: 'tag_name_conflict', message: 'dup' },
          { status: 409 },
        ),
      ),
    );
    render(
      <W>
        <TagsManagerModal opened onClose={() => {}} />
      </W>,
    );
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: /new tag/i }));
    await userEvent.type(within(dialog).getByRole('textbox', { name: /name/i }), 'Vocal');
    await userEvent.click(within(dialog).getByRole('button', { name: /^create$/i }));
    expect(await within(dialog).findByText(/already exists/i)).toBeInTheDocument();
  });
});
