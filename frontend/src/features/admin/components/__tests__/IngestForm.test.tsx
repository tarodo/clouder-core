import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { server } from '../../../../test/setup';
import { IngestForm } from '../IngestForm';
import { bpTokenStore } from '../../lib/bpTokenStore';

afterEach(() => {
  bpTokenStore.clear();
});

function ui(props: React.ComponentProps<typeof IngestForm>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <IngestForm {...props} />
      </MantineProvider>
    </QueryClientProvider>
  );
}

describe('IngestForm', () => {
  it('disables submit when no token', () => {
    render(
      ui({
        styleId: 1,
        styleName: 'Tech',
        weekYear: 2026,
        weekNumber: 5,
        onStarted: vi.fn(),
      }),
    );
    expect(screen.getByRole('button', { name: 'Start ingest' })).toBeDisabled();
  });

  it('submits standard range when override off', async () => {
    bpTokenStore.set('tok');
    let captured: unknown = null;
    server.use(
      http.post('http://localhost/admin/beatport/ingest', async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({
          run_id: 'r1',
          run_status: 'RAW_SAVED',
          processing_status: 'QUEUED',
          is_custom_range: false,
        });
      }),
    );
    const onStarted = vi.fn();
    render(
      ui({ styleId: 1, styleName: 'Tech', weekYear: 2026, weekNumber: 5, onStarted }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Start ingest' }));
    await waitFor(() => expect(onStarted).toHaveBeenCalledWith('r1'));
    expect(captured).toMatchObject({
      style_id: 1,
      week_year: 2026,
      week_number: 5,
      bp_token: 'tok',
    });
    expect(captured).not.toHaveProperty('period_start');
  });

  it('submits override range when toggled', async () => {
    bpTokenStore.set('tok');
    let captured: unknown = null;
    server.use(
      http.post('http://localhost/admin/beatport/ingest', async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({
          run_id: 'r1',
          run_status: 'RAW_SAVED',
          processing_status: 'QUEUED',
          is_custom_range: true,
        });
      }),
    );
    render(
      ui({ styleId: 1, styleName: 'Tech', weekYear: 2026, weekNumber: 5, onStarted: vi.fn() }),
    );
    await userEvent.click(screen.getByLabelText('Override date range'));
    fireEvent.change(screen.getByLabelText('period_end'), { target: { value: '2026-02-10' } });
    await userEvent.click(screen.getByRole('button', { name: 'Start ingest' }));
    await waitFor(() =>
      expect((captured as { period_end?: string })?.period_end).toBe('2026-02-10'),
    );
  });
});
