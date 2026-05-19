import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import i18n from '../../../../i18n';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { LabelTile } from '../LabelTile';

function renderTile(labelId: string | null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <MemoryRouter>
            <LabelTile labelId={labelId} styleId="dnb" />
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>
  );
}

describe('LabelTile', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('renders null when labelId is null', () => {
    renderTile(null);
    // No label content should render; Mantine still injects its own <style> tags
    // into the MantineProvider subtree, so the wrapping container is not
    // strictly empty. Assert on the absence of any link to a label detail page.
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
  });

  it('renders null on 404', async () => {
    server.use(
      http.get('http://localhost/labels/missing', () =>
        HttpResponse.json({ error_code: 'label_not_found', message: 'nope' }, { status: 404 }),
      ),
    );
    renderTile('missing');
    // Wait long enough for the query to settle, then assert nothing leaked through.
    await new Promise((r) => setTimeout(r, 200));
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.queryByText('library.tile.read_more')).not.toBeInTheDocument();
  });

  it('renders the label name when fetch succeeds', async () => {
    server.use(
      http.get('http://localhost/labels/abc', () =>
        HttpResponse.json({
          label_name: 'Fokuz',
          country: 'NL',
          tagline: 'soulful d&b',
          website: 'https://fokuzrecordings.com',
          soundcloud_url: 'https://soundcloud.com/fokuz',
        }),
      ),
    );
    renderTile('abc');
    await waitFor(() => expect(screen.getByText('Fokuz')).toBeInTheDocument());
    expect(screen.getByText('soulful d&b')).toBeInTheDocument();
  });
});
