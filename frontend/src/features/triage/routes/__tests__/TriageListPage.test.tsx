import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { http, HttpResponse } from 'msw';
import i18n from '../../../../i18n';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { TriageListPage } from '../TriageListPage';

function Wrapper({ children, initialEntries }: { children: React.ReactNode; initialEntries: string[] }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return (
    <MantineProvider theme={testTheme}>
      <ModalsProvider>
        <Notifications />
        <I18nextProvider i18n={i18n}>
          <QueryClientProvider client={qc}>
            <MemoryRouter initialEntries={initialEntries}>
              <Routes>
                <Route path="/triage/:styleId" element={children} />
              </Routes>
            </MemoryRouter>
          </QueryClientProvider>
        </I18nextProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

beforeEach(() => {
  tokenStore.set('TOK');
  server.use(
    http.get('http://localhost/styles', () =>
      HttpResponse.json({ items: [{ id: 's1', name: 'House' }], total: 1, limit: 200, offset: 0 }),
    ),
    http.get('http://localhost/styles/s1/triage/blocks', () =>
      HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
    ),
  );
});

describe('TriageListPage ?create=1', () => {
  it('opens the create dialog when ?create=1 is present', async () => {
    render(
      <Wrapper initialEntries={['/triage/s1?create=1']}>
        <TriageListPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
  });

  it('does not auto-open the dialog without the param', async () => {
    render(
      <Wrapper initialEntries={['/triage/s1']}>
        <TriageListPage />
      </Wrapper>,
    );
    // wait one tick for effects to flush
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });
});
