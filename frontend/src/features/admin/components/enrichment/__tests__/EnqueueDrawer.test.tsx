import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nextProvider } from 'react-i18next';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import i18n from '../../../../../i18n';
import { server } from '../../../../../test/setup';
import { tokenStore } from '../../../../../auth/tokenStore';
import { EnqueueDrawer } from '../EnqueueDrawer';

function renderDrawer(onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <Notifications />
          <EnqueueDrawer
            opened
            onClose={onClose}
            labelIds={['l1', 'l2']}
          />
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>
  );
}

describe('EnqueueDrawer', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('loads options and submits an enrich request', async () => {
    server.use(
      http.get('http://localhost/admin/labels/enrich/options', () =>
        HttpResponse.json({
          vendors: ['gemini', 'openai', 'tavily_deepseek'],
          prompt_versions: [{ slug: 'label_v3_app_fields', version: 'v1', is_default: true }],
          default_models: { gemini: 'gem', openai: 'gpt', tavily_deepseek: 'dsk' },
          merge: { vendor: 'deepseek', default_model: 'deepseek-chat' },
        }),
      ),
      http.post('http://localhost/admin/labels/enrich', async ({ request }) => {
        const body = await request.json() as any;
        expect(body.labels).toHaveLength(2);
        expect(body.prompt_slug).toBe('label_v3_app_fields');
        return HttpResponse.json({ run_id: 'r-x', queued_labels: 2 }, { status: 202 });
      }),
    );

    const onClose = vi.fn();
    renderDrawer(onClose);

    // The submit button is labeled "Enqueue" (no count interpolation in static text)
    await waitFor(() => expect(screen.getByRole('button', { name: /Enqueue/ })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /Enqueue/ }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
