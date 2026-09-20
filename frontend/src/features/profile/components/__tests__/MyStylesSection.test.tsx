import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { MyStylesSection } from '../MyStylesSection';

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <MyStylesSection />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const catalog = {
  items: [
    { id: 's1', name: 'Drum & Bass', selected: true, position: 0 },
    { id: 's2', name: 'House', selected: false, position: null },
  ],
  total: 2,
  limit: 200,
  offset: 0,
};

describe('MyStylesSection', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(
      http.get('http://localhost/styles', () => HttpResponse.json(catalog)),
    );
  });

  it('splits the catalog into selected and addable', async () => {
    renderSection();

    expect(await screen.findByText('Drum & Bass')).toBeDefined();
    expect(screen.getByText('House')).toBeDefined();
    expect(screen.queryByText(/Nothing selected/)).toBeNull();
  });

  it('adding a style PUTs the new selection with it appended', async () => {
    let body: { style_ids: string[] } | null = null;
    server.use(
      http.put('http://localhost/me/styles', async ({ request }) => {
        body = (await request.json()) as { style_ids: string[] };
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderSection();

    await screen.findByText('House');
    await userEvent.click(screen.getByRole('button', { name: /add House/i }));

    await waitFor(() => expect(body).toEqual({ style_ids: ['s1', 's2'] }));
  });

  it('removing a style PUTs the remainder', async () => {
    let body: { style_ids: string[] } | null = null;
    server.use(
      http.put('http://localhost/me/styles', async ({ request }) => {
        body = (await request.json()) as { style_ids: string[] };
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderSection();

    await screen.findByText('Drum & Bass');
    await userEvent.click(
      screen.getByRole('button', { name: /remove Drum & Bass/i }),
    );

    await waitFor(() => expect(body).toEqual({ style_ids: [] }));
  });

  it('shows the hint when nothing is selected', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          ...catalog,
          items: catalog.items.map((s) => ({ ...s, selected: false, position: null })),
        }),
      ),
    );
    renderSection();

    expect(await screen.findByText(/Nothing selected/)).toBeDefined();
  });
});
