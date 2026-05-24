import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { TrackTagsPopover } from '../TrackTagsPopover';

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

describe('TrackTagsPopover', () => {
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

  it('renders checkboxes for each tag and reflects current selection', async () => {
    render(
      <W>
        <TrackTagsPopover
          opened
          onClose={() => {}}
          target={<button>open</button>}
          trackId="t1"
          currentTagIds={['tg1']}
          onToggle={vi.fn()}
        />
      </W>,
    );
    const vocalRow = await screen.findByRole('checkbox', { name: /vocal/i });
    const darkRow = await screen.findByRole('checkbox', { name: /dark/i });
    expect(vocalRow).toBeChecked();
    expect(darkRow).not.toBeChecked();
  });

  it('calls onToggle with (tag, true) when an unchecked tag is clicked', async () => {
    const onToggle = vi.fn();
    render(
      <W>
        <TrackTagsPopover
          opened
          onClose={() => {}}
          target={<button>open</button>}
          trackId="t1"
          currentTagIds={[]}
          onToggle={onToggle}
        />
      </W>,
    );
    await userEvent.click(await screen.findByRole('checkbox', { name: /vocal/i }));
    expect(onToggle).toHaveBeenCalledWith(
      { id: 'tg1', name: 'Vocal', color: '#ff8800' },
      true,
    );
  });

  it('shows "Create" suggestion when search has no exact match', async () => {
    render(
      <W>
        <TrackTagsPopover
          opened
          onClose={() => {}}
          target={<button>open</button>}
          trackId="t1"
          currentTagIds={[]}
          onToggle={vi.fn()}
        />
      </W>,
    );
    await userEvent.type(
      await screen.findByPlaceholderText(/search.*create/i),
      'hyper',
    );
    expect(await screen.findByRole('button', { name: /create.*hyper/i })).toBeInTheDocument();
  });

  it('does NOT show "Create" suggestion when search matches an existing tag exactly', async () => {
    render(
      <W>
        <TrackTagsPopover
          opened
          onClose={() => {}}
          target={<button>open</button>}
          trackId="t1"
          currentTagIds={[]}
          onToggle={vi.fn()}
        />
      </W>,
    );
    await userEvent.type(
      await screen.findByPlaceholderText(/search.*create/i),
      'vocal',
    );
    expect(screen.queryByRole('button', { name: /create.*vocal/i })).toBeNull();
  });

  it('disables remaining checkboxes when 50 tags already attached', async () => {
    const manyIds = Array.from({ length: 50 }, (_, i) => `attached${i}`);
    render(
      <W>
        <TrackTagsPopover
          opened
          onClose={() => {}}
          target={<button>open</button>}
          trackId="t1"
          currentTagIds={manyIds}
          onToggle={vi.fn()}
        />
      </W>,
    );
    const dark = await screen.findByRole('checkbox', { name: /dark/i });
    expect(dark).toBeDisabled();
  });
});
