import { describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { testTheme } from '../../../../test/theme';
import { AdminCoveragePage } from '../AdminCoveragePage';

function style(clouderId: string, name: string, bpId: number, isHidden: boolean) {
  return {
    style_id: bpId,
    clouder_style_id: clouderId,
    style_name: name,
    is_hidden: isHidden,
    cells: [],
    spotify_weeks: [],
  };
}

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <AdminCoveragePage />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('AdminCoveragePage style visibility', () => {
  it('keeps hidden styles out of the matrix and toggles visibility via PATCH', async () => {
    const hidden = { 'uuid-bf': true, 'uuid-th': false };
    const patches: Array<{ id: string; body: unknown }> = [];
    server.use(
      http.get('http://localhost/admin/coverage', () =>
        HttpResponse.json({
          week_year: 2026,
          weeks_in_year: 52,
          correlation_id: 't',
          styles: [
            style('uuid-bf', 'Brazilian Funk', 100, hidden['uuid-bf']),
            style('uuid-th', 'Tech House', 90, hidden['uuid-th']),
          ],
        }),
      ),
      http.patch('http://localhost/admin/styles/:id', async ({ params, request }) => {
        const body = (await request.json()) as { is_hidden: boolean };
        const id = String(params.id) as keyof typeof hidden;
        patches.push({ id, body });
        hidden[id] = body.is_hidden;
        return HttpResponse.json({ style_id: id, is_hidden: body.is_hidden });
      }),
    );

    renderPage();

    expect(await screen.findByLabelText('Tech House week 1 empty')).toBeInTheDocument();
    expect(screen.queryByLabelText('Brazilian Funk week 1 empty')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /^styles/i }));
    expect(await screen.findByRole('checkbox', { name: 'Brazilian Funk' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Tech House' })).toBeChecked();

    await userEvent.click(screen.getByRole('checkbox', { name: 'Tech House' }));

    await waitFor(() =>
      expect(patches).toEqual([{ id: 'uuid-th', body: { is_hidden: true } }]),
    );
    await waitFor(() =>
      expect(screen.queryByLabelText('Tech House week 1 empty')).not.toBeInTheDocument(),
    );
  });
});
