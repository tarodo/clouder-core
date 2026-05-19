import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import i18n from '../../../../i18n';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { LabelPreferenceButtons } from '../LabelPreferenceButtons';

function renderButtons(current: 'liked' | 'disliked' | null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <LabelPreferenceButtons labelId="lbl-1" current={current} />
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>
  );
}

describe('LabelPreferenceButtons', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(
      http.put('http://localhost/labels/lbl-1/preference', () =>
        new HttpResponse(null, { status: 204 }),
      ),
    );
  });

  it('renders heart and cross icons with i18n aria labels', () => {
    renderButtons(null);
    expect(screen.getByRole('button', { name: /^like label$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /dislike label/i })).toBeInTheDocument();
  });

  it('clicking heart on null state issues liked PUT', async () => {
    let capturedBody: unknown = null;
    server.use(
      http.put('http://localhost/labels/lbl-1/preference', async ({ request }) => {
        capturedBody = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderButtons(null);
    fireEvent.click(screen.getByRole('button', { name: /^like label$/i }));
    await waitFor(() => expect(capturedBody).toEqual({ status: 'liked' }));
  });

  it('clicking active heart issues none PUT', async () => {
    let capturedBody: unknown = null;
    server.use(
      http.put('http://localhost/labels/lbl-1/preference', async ({ request }) => {
        capturedBody = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderButtons('liked');
    fireEvent.click(screen.getByRole('button', { name: /remove preference/i }));
    await waitFor(() => expect(capturedBody).toEqual({ status: 'none' }));
  });
});
