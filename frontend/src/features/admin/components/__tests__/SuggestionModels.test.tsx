import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { server } from '../../../../test/setup';
import { SuggestionModels } from '../SuggestionModels';
import type { components } from '../../../../api/schema';

type Analysis = components['schemas']['AnalysisStatus'];
type Item = Analysis['models']['items'][number];

const NO_MODEL = {
  version: 0,
  trained_at: null,
  retrain_pending: false,
  labels_since_training: 0,
  n_labels: null,
  n_keep: null,
  rows_total: null,
  keep_auc: null,
  category_bacc: null,
  n_classes: null,
  first_hit: null,
  first_n: null,
  max_rss_mb: null,
  predictions: 0,
};

const item = (style_name: string, over: Partial<Item> = {}): Item => ({
  user_id: 'a'.repeat(32),
  user_name: 'Roman',
  style_id: style_name.toLowerCase(),
  style_name,
  ...NO_MODEL,
  ...over,
});

const ITEMS: Item[] = [
  item('Techno', {
    version: 3,
    trained_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
    labels_since_training: null,
    n_labels: 600,
    n_keep: 210,
    rows_total: 900,
    keep_auc: 0.81234,
    category_bacc: 0.6789,
    n_classes: 4,
    first_hit: 0.456,
    first_n: 48,
    max_rss_mb: 2700,
    predictions: 12345,
  }),
  item('Minimal', {
    version: 1,
    trained_at: new Date().toISOString(),
    labels_since_training: null,
    n_labels: 150,
    n_keep: 60,
    rows_total: 150,
    keep_auc: 0.7,
    first_n: 12,
    max_rss_mb: 1200,
  }),
  item('House', { retrain_pending: true }),
  item('Garage', { version: 1, trained_at: new Date().toISOString(), labels_since_training: null }),
  item('Trance', { labels_since_training: 37 }),
];

function renderWith(items: Item[]) {
  server.use(
    http.get('http://localhost/admin/analysis/status', () =>
      HttpResponse.json({ models: { count: 0, last_trained_at: null, items } }),
    ),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <SuggestionModels />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const row = async (style: string) => (await screen.findByText(style)).closest('tr')!;

describe('SuggestionModels', () => {
  it('shows a trained model with capped labels, its metrics and high memory', async () => {
    renderWith(ITEMS);
    const techno = await row('Techno');
    expect(techno).toHaveTextContent(/v3 · 2 hours ago/);
    expect(techno).toHaveTextContent('600 of 900 (210 keep)');
    expect(techno).toHaveTextContent('0.812');
    expect(techno).toHaveTextContent('0.679 · 4 cat.');
    expect(techno).toHaveTextContent('46 % of 48');
    expect(techno).toHaveTextContent('12,345');
    expect(screen.getByText('2.6 / 3.0 GB')).toHaveAttribute('data-warn', 'true');
  });

  it('shows the first button under 20 taps, no category head and normal memory', async () => {
    renderWith(ITEMS);
    const minimal = await row('Minimal');
    expect(minimal).toHaveTextContent('150 (60 keep)');
    expect(minimal).toHaveTextContent('— (12 of 20)');
    expect(minimal).toHaveTextContent('0.700—');
    expect(screen.getByText('1.2 / 3.0 GB')).not.toHaveAttribute('data-warn');
  });

  it('shows a queued retrain and a pair waiting for labels', async () => {
    renderWith(ITEMS);
    // no model: a bare dash in every metric cell, the first button too
    expect(await row('House')).toHaveTextContent('RomanHousequeued————0—');
    expect(await row('Trance')).toHaveTextContent('RomanTrancewaiting for labels: 37 / 150————0—');
    // a model without first-button taps yet: 0 of 20
    expect(await row('Garage')).toHaveTextContent('— (0 of 20)');
  });

  it('says so when there are no models', async () => {
    renderWith([]);
    expect(await screen.findByText('Suggestion models')).toBeInTheDocument();
    expect(await screen.findByText('No models yet')).toBeInTheDocument();
  });
});
