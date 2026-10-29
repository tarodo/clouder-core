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

function renderTile(labelId: string | null, labelName: string | null = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <MemoryRouter>
            <LabelTile labelId={labelId} labelName={labelName} />
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
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('renders name + preference buttons when enrichment is missing (minimal payload)', async () => {
    server.use(
      http.get('http://localhost/labels/minimal', () =>
        HttpResponse.json({ label_name: 'Fokuz', my_preference: null }),
      ),
    );
    renderTile('minimal', 'fallback');
    await waitFor(() => expect(screen.getByText('Fokuz')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /^like label$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^dislike label$/i })).toBeInTheDocument();
    expect(screen.queryByText('soulful d&b')).not.toBeInTheDocument();
  });

  it("shows the user's numbers and that there is no description yet", async () => {
    server.use(
      http.get('http://localhost/labels/bare', () =>
        HttpResponse.json({
          label_name: 'Exit Strategy',
          my_preference: null,
          stats: { tracks: 412, in_categories: 9, in_playlists: 0 },
        }),
      ),
    );
    renderTile('bare');
    expect(await screen.findByText('412')).toBeInTheDocument();
    expect(screen.getByText('9')).toBeInTheDocument();
    expect(screen.getByText('in categories')).toBeInTheDocument();
    expect(screen.getByText('No description yet')).toBeInTheDocument();
  });

  it('renders the label name + full content when fetch succeeds', async () => {
    server.use(
      http.get('http://localhost/labels/abc', () =>
        HttpResponse.json({
          label_name: 'Fokuz',
          country: 'NL',
          tagline: 'soulful d&b',
          website: 'https://fokuzrecordings.com',
          soundcloud_url: 'https://soundcloud.com/fokuz',
          my_preference: null,
        }),
      ),
    );
    renderTile('abc', 'fallback name');
    await waitFor(() => expect(screen.getByText('Fokuz')).toBeInTheDocument());
    expect(screen.getByText('soulful d&b')).toBeInTheDocument();
    // Country as a plain ISO code: flag emoji render as letter pairs on Windows anyway.
    expect(document.body.textContent).not.toMatch(/\p{Regional_Indicator}/u);
  });

  it('renders the label name as a link to the top-level label page', async () => {
    server.use(
      http.get('http://localhost/labels/linked', () =>
        HttpResponse.json({ label_name: 'Linked', my_preference: null }),
      ),
    );
    renderTile('linked', 'fallback');
    await waitFor(() => expect(screen.getByText('Linked')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: 'Linked' })).toHaveAttribute('href', '/labels/linked');
  });
});

describe('LabelTile AI reputation', () => {
  it('marks the label', async () => {
    server.use(
      http.get('http://localhost/labels/ai', () =>
        HttpResponse.json({ label_name: 'Abstrato', my_preference: null, ai: { level: 3 as const, ai: 80, checked: 87, total: 869 } }),
      ),
    );
    renderTile('ai', 'fallback');
    expect(await screen.findByLabelText('AI level 3')).toBeInTheDocument();
  });
});
