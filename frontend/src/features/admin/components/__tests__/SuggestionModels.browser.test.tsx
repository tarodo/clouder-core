import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { page } from 'vitest/browser';
import '../../../../i18n';
import { sampleSuggestionModels } from '../../../../demo/samples';
import { SuggestionModels } from '../SuggestionModels';

describe('SuggestionModels layout', () => {
  test('scrolls inside its own container at phone width, never the page', async () => {
    await page.viewport(390, 800);
    const qc = new QueryClient();
    qc.setQueryData(['admin', 'analysisStatus'], {
      models: { count: 3, last_trained_at: null, items: sampleSuggestionModels() },
    });
    render(
      <QueryClientProvider client={qc}>
        <MantineProvider>
          <div style={{ padding: 16 }}>
            <SuggestionModels />
          </div>
        </MantineProvider>
      </QueryClientProvider>,
    );
    let scroller = (await screen.findByText('Afro House')).closest('table')!.parentElement!;
    while (!['auto', 'scroll'].includes(getComputedStyle(scroller).overflowX)) {
      scroller = scroller.parentElement!;
    }
    expect(scroller.scrollWidth).toBeGreaterThan(scroller.clientWidth);
    expect(scroller.getBoundingClientRect().right).toBeLessThanOrEqual(window.innerWidth);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
  });
});
