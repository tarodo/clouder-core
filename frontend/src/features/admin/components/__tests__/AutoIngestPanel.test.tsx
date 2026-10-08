import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { server } from '../../../../test/setup';
import { AutoIngestPanel, autoIngestPollInterval } from '../AutoIngestPanel';
import type { AutoIngestState } from '../../../../api/autoIngest';

const PLANNED = '2026-10-08T14:30:00+00:00';

function state(over: Partial<AutoIngestState['settings']> = {}): AutoIngestState {
  return {
    running: false,
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

function renderPanel(qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
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


describe('AutoIngestPanel progress', () => {
  function running(over: Partial<AutoIngestState> = {}): AutoIngestState {
    return {
      ...state(),
      running: true,
      last_run: {
        at: '2026-10-08T03:50:00+00:00', manual: true, in_progress: true,
        current: { style_id: 81, week_year: 2026, week_number: 38 }, total: 3,
        pairs: [{ style_id: 6, week_year: 2026, week_number: 38, ok: true, run_id: 'r', item_count: 1465 }],
      },
      ...over,
    };
  }

  it('shows the period being fetched and blocks a second run', async () => {
    serve(running());
    renderPanel();
    expect(await screen.findByText('Funky House · 2026-W38 (2/3)')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run now' })).toBeDisabled();
  });

  it('shows the login step before the first period', async () => {
    serve(running({ last_run: { at: '2026-10-08T03:50:00+00:00', manual: true, in_progress: true,
                                current: null, total: null, pairs: [] } }));
    renderPanel();
    expect(await screen.findByText('Logging in to Beatport…')).toBeInTheDocument();
  });

  it('a progress record without a lease is an interrupted run', async () => {
    serve(running({ running: false }));
    renderPanel();
    expect(await screen.findByText(/Interrupted/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run now' })).toBeEnabled();
  });

  it('polls every 10 s while a run holds the lease or right after Run now', () => {
    const idle = state();
    expect(autoIngestPollInterval(running(), null, 0)).toBe(10_000);
    expect(autoIngestPollInterval(idle, null, 0)).toBe(false);
    expect(autoIngestPollInterval(idle, 1_000, 60_000)).toBe(10_000); // waiting for the run to start
    expect(autoIngestPollInterval(idle, 1_000, 200_000)).toBe(false);
    expect(autoIngestPollInterval(undefined, null, 0)).toBe(false);
  });

  it('polling during a run keeps an unsaved edit', async () => {
    let calls = 0;
    server.use(
      http.get('http://localhost/admin/auto-ingest', () => {
        calls += 1; // last_run changes on every poll, the settings do not
        return HttpResponse.json(running({ last_run: { ...running().last_run!, total: 2 + calls } }));
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPanel(qc);
    const periods = await screen.findByLabelText('Periods per run');
    await userEvent.clear(periods);
    await userEvent.type(periods, '7');
    await qc.refetchQueries({ queryKey: ['admin', 'autoIngest'] });
    await waitFor(() => expect(calls).toBeGreaterThan(1));
    expect(screen.getByLabelText('Periods per run')).toHaveValue('7');
  });
});
