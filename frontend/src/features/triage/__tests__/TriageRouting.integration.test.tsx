import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router';
import { TriageIndexRedirect } from '../routes/TriageIndexRedirect';
import { TriageDetailStub } from '../routes/TriageDetailStub';
import { TriageListPage } from '../routes/TriageListPage';

const server = setupServer();
beforeEach(() => {
  server.listen({ onUnhandledRequest: 'error' });
  localStorage.clear();
});
afterEach(() => {
  server.resetHandlers();
  server.close();
});

function renderApp(initialPath: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <MantineProvider>
        <QueryClientProvider client={qc}>
          <ModalsProvider>
            <Notifications />
            <Routes>
              <Route path="/triage" element={<TriageIndexRedirect />} />
              <Route
                path="/triage/:styleId"
                element={<TriageListPage />}
              />
              <Route
                path="/triage/:styleId/:id"
                element={<TriageDetailStub />}
              />
            </Routes>
          </ModalsProvider>
        </QueryClientProvider>
      </MantineProvider>
    </MemoryRouter>,
  );
}

const stylesResponse = {
  items: [
    { id: 's1', name: 'House' },
    { id: 's2', name: 'Techno' },
  ],
  total: 2,
  limit: 200,
  offset: 0,
};

describe('Triage routing', () => {
  it('redirects index → first style when localStorage empty', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json(stylesResponse),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );

    renderApp('/triage');
    // Page title for the list page lands once the redirect resolves.
    expect(
      await screen.findByRole('heading', { name: /^Triage$/ }),
    ).toBeInTheDocument();
  });

  it('redirects index → stored style when set', async () => {
    localStorage.setItem('clouder.lastTriageStyleId', 's2');
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json(stylesResponse),
      ),
      http.get('http://localhost/styles/s2/triage/blocks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    renderApp('/triage');
    // The list page mounts and the heading appears. Heading copy is shared
    // across styles; rely on the StyleSelector reflecting the chosen style
    // (Mantine Select renders the selected label as text).
    await screen.findByRole('heading', { name: /^Triage$/ });
    expect(await screen.findByDisplayValue('Techno')).toBeInTheDocument();
  });

  it('detail stub renders coming-soon EmptyState', async () => {
    renderApp('/triage/s1/abc');
    expect(
      await screen.findByText(/coming soon/i),
    ).toBeInTheDocument();
  });
});
