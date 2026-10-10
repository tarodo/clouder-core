import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { page } from 'vitest/browser';
import '../../../../i18n';
import { AutoIngestPanel } from '../AutoIngestPanel';
import { AUTO_INGEST_KEY } from '../../hooks/useAutoIngest';

function seeded(mode: 'fixed' | 'random') {
  const qc = new QueryClient();
  qc.setQueryData(AUTO_INGEST_KEY, {
    settings: {
      enabled: false, mode, fixed_times: ['09:00'], runs_per_day: 3, timezone: 'UTC',
      periods_per_run: 3, backfill_floor: '2026-01-03', updated_at: '2026-10-07T10:00:00+00:00',
    },
    planned_runs: [], last_run: null, running: false,
    due_week: { week_year: 2026, week_number: 39 }, stuck: [],
  });
  return qc;
}

describe('AutoIngestPanel layout', () => {
  test.each(['fixed', 'random'] as const)('fields side by side line up on desktop (%s)', async (mode) => {
    await page.viewport(1280, 900);
    const { container } = render(
      <QueryClientProvider client={seeded(mode)}>
        <MantineProvider>
          <AutoIngestPanel />
        </MantineProvider>
      </QueryClientProvider>,
    );
    const ui = within(container);
    // Mantine Select labels both its input and its listbox: take the input.
    const top = (label: string) => ui.getAllByLabelText(label)[0]!.getBoundingClientRect().top;
    await ui.findAllByLabelText('Timezone');
    expect(top(mode === 'fixed' ? 'Times' : 'Runs per day')).toBeCloseTo(top('Timezone'), 0);
    expect(top('Periods per run')).toBeCloseTo(top('Backfill floor'), 0);
  });

  test('fits a phone-width column without horizontal overflow', async () => {
    await page.viewport(375, 800);
    const qc = new QueryClient();
    qc.setQueryData(AUTO_INGEST_KEY, {
      settings: {
        enabled: true, mode: 'fixed', fixed_times: ['09:00', '15:00', '21:00'], runs_per_day: 3,
        timezone: 'America/Argentina/ComodRivadavia', periods_per_run: 3,
        backfill_floor: '2026-01-03', updated_at: '2026-10-07T10:00:00+00:00',
      },
      planned_runs: ['2026-10-08T09:00:00+00:00', '2026-10-08T15:00:00+00:00'],
      last_run: {
        at: '2026-10-07T09:00:00+00:00', manual: true, ok: false,
        pairs: [{ style_id: 96, week_year: 2026, week_number: 39, ok: false,
                  error: 'BeatportUnavailableError 503 after three retries upstream' }],
      },
      due_week: { week_year: 2026, week_number: 39 },
      stuck: [],
      running: false,
    });
    render(
      <QueryClientProvider client={qc}>
        <MantineProvider>
          <div data-testid="column" style={{ width: 343 }}>
            <AutoIngestPanel />
          </div>
        </MantineProvider>
      </QueryClientProvider>,
    );
    const times = await screen.findByLabelText('Times');
    // One field per row on a phone: the inputs take the column's width.
    expect(times.getBoundingClientRect().width).toBeGreaterThan(280);
    const column = screen.getByTestId('column');
    const card = column.firstElementChild as HTMLElement;
    expect(card.scrollWidth).toBeLessThanOrEqual(card.clientWidth);
    const right = column.getBoundingClientRect().right;
    for (const el of card.querySelectorAll('input, button')) {
      expect(el.getBoundingClientRect().right).toBeLessThanOrEqual(right + 0.5);
    }
  });
});
