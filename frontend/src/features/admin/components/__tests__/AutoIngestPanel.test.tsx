import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { server } from '../../../../test/setup';
import { AutoIngestPanel } from '../AutoIngestPanel';
import type { AutoIngestState } from '../../../../api/autoIngest';

const PLANNED = '2026-10-08T14:30:00+00:00';

function state(over: Partial<AutoIngestState['settings']> = {}): AutoIngestState {
  return {
    settings: {
      enabled: true,
      mode: 'fixed',
      fixed_times: ['09:00', '21:00'],
      runs_per_day: 3,
      timezone: 'UTC',
      periods_per_run: 3,
      backfill_floor: '2026-01-03',
      updated_at: '2026-10-07T10:00:00+00:00',
      ...over,
    },
    planned_runs: [PLANNED],
    last_run: {
      at: '2026-10-07T09:00:00+00:00',
      manual: false,
      ok: false,
      pairs: [
        { style_id: 81, week_year: 2026, week_number: 39, ok: true, run_id: 'r1', item_count: 40 },
        { style_id: 96, week_year: 2026, week_number: 39, ok: false, error: 'BeatportUnavailableError 503' },
      ],
    },
    due_week: { week_year: 2026, week_number: 39 },
    stuck: [
      { style_id: 12, week_year: 2026, week_number: 2, last_attempt_at: null, last_error: 'HTTPError 404' },
    ],
  };
}

function serve(initial: AutoIngestState) {
  const calls: { put: unknown[]; run: number } = { put: [], run: 0 };
  server.use(
    http.get('http://localhost/admin/auto-ingest', () => HttpResponse.json(initial)),
    http.put('http://localhost/admin/auto-ingest', async ({ request }) => {
      const body = (await request.json()) as AutoIngestState['settings'];
      calls.put.push(body);
      return HttpResponse.json({ ...initial, settings: { ...initial.settings, ...body } });
    }),
    http.post('http://localhost/admin/auto-ingest/run', () => {
      calls.run += 1;
      return HttpResponse.json({ accepted: true }, { status: 202 });
    }),
  );
  return calls;
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <AutoIngestPanel styleNames={new Map([[81, 'Funky House'], [96, 'Mainstage']])} />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('AutoIngestPanel', () => {
  it('renders the saved settings', async () => {
    serve(state());
    renderPanel();
    expect(await screen.findByLabelText('Times')).toHaveValue('09:00, 21:00');
    expect(screen.getByRole('switch', { name: 'Enabled' })).toBeChecked();
    expect(screen.getByLabelText('Periods per run')).toHaveValue('3');
    expect(screen.getByLabelText('Backfill floor')).toHaveValue('2026-01-03');
  });

  it('switching to random shows runs per day instead of times', async () => {
    serve(state());
    renderPanel();
    await screen.findByLabelText('Times');
    await userEvent.click(screen.getByText('Random times'));
    expect(screen.queryByLabelText('Times')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Runs per day')).toHaveValue('3');
  });

  it('saves the edited settings', async () => {
    const calls = serve(state());
    renderPanel();
    const periods = await screen.findByLabelText('Periods per run');
    await userEvent.clear(periods);
    await userEvent.type(periods, '5');
    await userEvent.clear(screen.getByLabelText('Times'));
    await userEvent.type(screen.getByLabelText('Times'), '21:00, 08:30');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(calls.put).toHaveLength(1));
    expect(calls.put[0]).toEqual({
      enabled: true,
      mode: 'fixed',
      fixed_times: ['21:00', '08:30'],
      runs_per_day: 3,
      timezone: 'UTC',
      periods_per_run: 5,
      backfill_floor: '2026-01-03',
    });
  });

  it('an invalid time disables Save with a message', async () => {
    const calls = serve(state());
    renderPanel();
    const times = await screen.findByLabelText('Times');
    await userEvent.clear(times);
    await userEvent.type(times, '25:00');
    expect(screen.getByText('Use HH:MM, 1–12 distinct times, comma-separated.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(calls.put).toHaveLength(0);
  });

  it('a never-saved form starts in the browser timezone', async () => {
    serve(state({ updated_at: null }));
    renderPanel();
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(await screen.findByLabelText('Timezone')).toHaveValue(zone);
  });

  it('Run now starts a run', async () => {
    const calls = serve(state({ enabled: false }));
    renderPanel();
    await userEvent.click(await screen.findByRole('button', { name: 'Run now' }));
    await waitFor(() => expect(calls.run).toBe(1));
  });

  it('shows planned runs, last run outcomes and stuck pairs', async () => {
    serve(state());
    renderPanel();
    expect(await screen.findByText(new Date(PLANNED).toLocaleString())).toBeInTheDocument();
    expect(screen.getByText(/Funky House · 2026-W39 — 40 releases/)).toBeInTheDocument();
    expect(screen.getByText(/Mainstage · 2026-W39 — BeatportUnavailableError 503/)).toBeInTheDocument();
    expect(screen.getByText(/Style 12 · 2026-W2 — HTTPError 404/)).toBeInTheDocument();
    expect(screen.getByText('Due week: 2026-W39')).toBeInTheDocument();
  });
});
