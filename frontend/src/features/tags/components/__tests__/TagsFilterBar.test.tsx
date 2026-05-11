import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { TagsFilterBar } from '../TagsFilterBar';

function W({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  return (
    <MantineProvider>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </MantineProvider>
  );
}

describe('TagsFilterBar', () => {
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

  it('does not render the match toggle when nothing selected', async () => {
    render(
      <W>
        <TagsFilterBar selectedIds={[]} match="all" onChange={() => {}} />
      </W>,
    );
    expect(screen.queryByRole('radio', { name: /any/i })).toBeNull();
    expect(screen.queryByRole('radio', { name: /^all$/i })).toBeNull();
  });

  it('renders the match toggle with at least one tag selected', async () => {
    render(
      <W>
        <TagsFilterBar selectedIds={['tg1']} match="all" onChange={() => {}} />
      </W>,
    );
    expect(await screen.findByRole('radio', { name: /any/i })).toBeInTheDocument();
  });

  it('emits onChange when match flipped', async () => {
    const onChange = vi.fn();
    render(
      <W>
        <TagsFilterBar selectedIds={['tg1']} match="all" onChange={onChange} />
      </W>,
    );
    await userEvent.click(await screen.findByRole('radio', { name: /any/i }));
    expect(onChange).toHaveBeenCalledWith({ selectedIds: ['tg1'], match: 'any' });
  });
});
