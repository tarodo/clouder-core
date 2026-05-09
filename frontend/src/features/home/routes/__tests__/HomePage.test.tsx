import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { http, HttpResponse } from 'msw';
import i18n from '../../../../i18n';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import {
  LAST_CURATE_LOCATION_KEY,
  LAST_CURATE_STYLE_KEY,
} from '../../../curate/lib/lastCurateLocation';
import { HomePage } from '../HomePage';

function Wrapper({
  children,
  initialEntries = ['/'],
}: {
  children: React.ReactNode;
  initialEntries?: string[];
}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return (
    <MantineProvider theme={testTheme}>
      <Notifications />
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={initialEntries}>
            <Routes>
              <Route path="/" element={children} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>
  );
}

function block(
  id: string,
  styleId: string,
  styleName: string,
  status: 'IN_PROGRESS' | 'FINALIZED',
  updatedAt: string,
  count = 10,
) {
  return {
    id,
    style_id: styleId,
    style_name: styleName,
    name: id,
    date_from: '2026-05-04',
    date_to: '2026-05-10',
    status,
    created_at: '2026-05-04T00:00:00Z',
    updated_at: updatedAt,
    finalized_at: status === 'FINALIZED' ? updatedAt : null,
    track_count: count,
  };
}

beforeEach(() => {
  tokenStore.set('TOK');
  localStorage.clear();
});

describe('HomePage', () => {
  it('renders aggregated counters across two styles', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [
            { id: 's1', name: 'House' },
            { id: 's2', name: 'Techno' },
          ],
          total: 2,
          limit: 200,
          offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [block('b1', 's1', 'House', 'IN_PROGRESS', '2026-05-08T00:00:00Z', 30)],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s2/triage/blocks', () =>
        HttpResponse.json({
          items: [block('b2', 's2', 'Techno', 'IN_PROGRESS', '2026-05-09T00:00:00Z', 50)],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      ),
    );
    render(
      <Wrapper>
        <HomePage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('80')).toBeInTheDocument());
    expect(screen.getByText('2')).toBeInTheDocument(); // active blocks count
  });

  it('uses localStorage to render the curate resume hero', async () => {
    localStorage.setItem(LAST_CURATE_STYLE_KEY, 's1');
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({
        s1: { blockId: 'b1', bucketId: 'bk1', updatedAt: new Date().toISOString() },
      }),
    );
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [{ id: 's1', name: 'House' }],
          total: 1,
          limit: 200,
          offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [block('b1', 's1', 'House', 'IN_PROGRESS', '2026-05-08T00:00:00Z', 30)],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      ),
    );
    render(
      <Wrapper>
        <HomePage />
      </Wrapper>,
    );
    await waitFor(() => {
      const link = screen.getByRole('link', { name: /continue/i });
      expect(link.getAttribute('href')).toBe('/curate/s1/b1/bk1');
    });
  });

  it('falls back to triage and clears localStorage when stored block is FINALIZED', async () => {
    localStorage.setItem(LAST_CURATE_STYLE_KEY, 's1');
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({
        s1: { blockId: 'b1', bucketId: 'bk1', updatedAt: new Date().toISOString() },
      }),
    );
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [{ id: 's1', name: 'House' }],
          total: 1,
          limit: 200,
          offset: 0,
        }),
      ),
      // Server only returns IN_PROGRESS blocks (per status=IN_PROGRESS query); b1 is FINALIZED so it's absent.
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [block('b2', 's1', 'House', 'IN_PROGRESS', '2026-05-09T00:00:00Z', 12)],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      ),
    );
    render(
      <Wrapper>
        <HomePage />
      </Wrapper>,
    );
    await waitFor(() => {
      const link = screen.getByRole('link', { name: /open block/i });
      expect(link.getAttribute('href')).toBe('/triage/s1/b2');
    });
    expect(JSON.parse(localStorage.getItem(LAST_CURATE_LOCATION_KEY) ?? '{}')).toEqual({});
  });

  it('shows the create-first CTA when there are no IN_PROGRESS blocks', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [{ id: 's1', name: 'House' }],
          total: 1,
          limit: 200,
          offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <HomePage />
      </Wrapper>,
    );
    await waitFor(() => {
      const link = screen.getByRole('link', { name: /create first/i });
      expect(link.getAttribute('href')).toBe('/triage?create=1');
    });
  });

  it('renders the warning alert when one style query 500s', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [
            { id: 's1', name: 'House' },
            { id: 's2', name: 'Techno' },
          ],
          total: 2,
          limit: 200,
          offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [block('b1', 's1', 'House', 'IN_PROGRESS', '2026-05-08T00:00:00Z', 30)],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s2/triage/blocks', () =>
        HttpResponse.json(
          { error_code: 'server', message: 'boom', correlation_id: 'x' },
          { status: 500 },
        ),
      ),
    );
    render(
      <Wrapper>
        <HomePage />
      </Wrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Some styles failed to load/)).toBeInTheDocument(),
    );
    expect(screen.getAllByText('30').length).toBeGreaterThan(0);
  });

  it('renders the no-styles empty state', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <HomePage />
      </Wrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/No styles assigned yet/)).toBeInTheDocument(),
    );
  });

  it('renders the inline error with retry when /styles fails', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json(
          { error_code: 'server', message: 'boom', correlation_id: 'x' },
          { status: 500 },
        ),
      ),
    );
    render(
      <Wrapper>
        <HomePage />
      </Wrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Couldn't load your dashboard/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
    expect(screen.getByText(/Reference: x/)).toBeInTheDocument();
  });
});
