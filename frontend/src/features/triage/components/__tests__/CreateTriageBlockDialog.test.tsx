import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

// Mantine's DatePickerInput renders as a button-like trigger that opens a
// popover calendar — userEvent.type cannot drive it under jsdom. Replace it
// with a plain text input that parses the "YYYY-MM-DD – YYYY-MM-DD" string
// and forwards a [Date, Date] tuple to the form, matching the production
// onChange contract.
vi.mock('@mantine/dates', async () => {
  const React = await import('react');
  type Props = {
    label?: string;
    onChange?: (value: [Date | null, Date | null]) => void;
    error?: React.ReactNode;
    description?: React.ReactNode;
    placeholder?: string;
  };
  const DatePickerInput = ({
    label,
    onChange,
    error,
    description,
    placeholder,
  }: Props) => {
    // Track raw typed text locally so userEvent.type works key-by-key without
    // each intermediate value being clobbered by the parent form state.
    const [text, setText] = React.useState('');
    return (
      <div>
        <label>
          {label}
          <input
            type="text"
            placeholder={placeholder}
            value={text}
            onChange={(e) => {
              const raw = e.target.value;
              setText(raw);
              const parts = raw.split(' – ');
              if (parts.length === 2 && parts[0] && parts[1]) {
                const a = new Date(parts[0].trim());
                const b = new Date(parts[1].trim());
                if (
                  !Number.isNaN(a.getTime()) &&
                  !Number.isNaN(b.getTime())
                ) {
                  onChange?.([a, b]);
                  return;
                }
              }
              onChange?.([null, null]);
            }}
          />
        </label>
        {description ? <div>{description}</div> : null}
        {error ? <div role="alert">{error}</div> : null}
      </div>
    );
  };
  return { DatePickerInput };
});

import { CreateTriageBlockDialog } from '../CreateTriageBlockDialog';

// Today = Tue 2026-10-20, inside Saturday-week 42 (Oct 17–23).
const TODAY = new Date('2026-10-20T12:00:00Z');

function blockSummary(dateTo: string) {
  return {
    id: `b-${dateTo}`,
    style_id: 's1',
    style_name: 'House',
    name: 'x',
    date_from: dateTo,
    date_to: dateTo,
    status: 'FINALIZED',
    created_at: 'now',
    updated_at: 'now',
    finalized_at: null,
    track_count: 0,
  };
}

const created = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'House W40',
  date_from: '2026-10-03',
  date_to: '2026-10-09',
  status: 'IN_PROGRESS',
  created_at: 'now',
  updated_at: 'now',
  finalized_at: null,
  buckets: [],
};

const server = setupServer();
let existingDateTos: string[];
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(TODAY);
  // Latest block ends Fri Oct 2 (end of W39) → default week is W40 (Oct 3–9).
  existingDateTos = ['2026-09-25', '2026-10-02'];
  server.listen({ onUnhandledRequest: 'error' });
  server.use(
    http.get('http://localhost/styles/s1/triage/blocks', () =>
      HttpResponse.json({
        items: existingDateTos.map(blockSummary),
        total: existingDateTos.length,
        limit: 50,
        offset: 0,
      }),
    ),
  );
});
afterEach(() => {
  server.resetHandlers();
  server.close();
  vi.useRealTimers();
});

function renderDialog(props: Partial<React.ComponentProps<typeof CreateTriageBlockDialog>> = {}) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  const utils = render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <Notifications />
        <CreateTriageBlockDialog
          opened
          onClose={vi.fn()}
          styleId="s1"
          styleName="House"
          {...props}
        />
      </QueryClientProvider>
    </MantineProvider>,
  );
  return { qc, ...utils };
}

const nameValue = () => (screen.getByLabelText('Name') as HTMLInputElement).value;

function capturePost() {
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.post('http://localhost/triage/blocks', async ({ request }) => {
      bodies.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json(created, { status: 201 });
    }),
  );
  return bodies;
}

describe('CreateTriageBlockDialog', () => {
  it('proposes the week after the latest block and names it by Saturday-week', async () => {
    renderDialog();
    expect(await screen.findByText('W40 · Oct 3 – Oct 9, 2026')).toBeInTheDocument();
    await waitFor(() => expect(nameValue()).toBe('House W40'));
  });

  it('proposes the last finished week when the style has no blocks', async () => {
    existingDateTos = [];
    renderDialog();
    expect(await screen.findByText('W41 · Oct 10 – Oct 16, 2026')).toBeInTheDocument();
  });

  it('submits the proposed week as the date window', async () => {
    const onClose = vi.fn();
    const bodies = capturePost();
    renderDialog({ onClose });
    await screen.findByText('W40 · Oct 3 – Oct 9, 2026');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(bodies[0]).toMatchObject({
      style_id: 's1',
      name: 'House W40',
      date_from: '2026-10-03',
      date_to: '2026-10-09',
    });
  });

  it('arrows step whole weeks and stop at the current week', async () => {
    renderDialog();
    await screen.findByText('W40 · Oct 3 – Oct 9, 2026');
    const next = screen.getByRole('button', { name: 'Next week' });

    await userEvent.click(next);
    expect(screen.getByText('W41 · Oct 10 – Oct 16, 2026')).toBeInTheDocument();
    await userEvent.click(next);
    expect(screen.getByText('W42 · Oct 17 – Oct 23, 2026')).toBeInTheDocument();
    expect(next).toBeDisabled();
    await waitFor(() => expect(nameValue()).toBe('House W42'));

    await userEvent.click(screen.getByRole('button', { name: 'Previous week' }));
    expect(screen.getByText('W41 · Oct 10 – Oct 16, 2026')).toBeInTheDocument();
    expect(next).toBeEnabled();
  });

  it('a manual range in advanced options overrides the week', async () => {
    const onClose = vi.fn();
    const bodies = capturePost();
    renderDialog({ onClose });
    await screen.findByText('W40 · Oct 3 – Oct 9, 2026');

    await userEvent.click(screen.getByText(/advanced options/i));
    await userEvent.type(screen.getByLabelText('Window'), '2026-10-05 – 2026-10-20');

    expect(await screen.findByText('Custom range · Oct 5 – Oct 20, 2026')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(bodies[0]).toMatchObject({
      name: 'House W40',
      date_from: '2026-10-05',
      date_to: '2026-10-20',
    });
  });

  it('preserves a user-edited name across week changes', async () => {
    renderDialog();
    await screen.findByText('W40 · Oct 3 – Oct 9, 2026');
    const nameInput = screen.getByLabelText('Name') as HTMLInputElement;
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, 'My Custom');
    await userEvent.click(screen.getByRole('button', { name: 'Previous week' }));
    await waitFor(() => expect(nameInput.value).toBe('My Custom'));
  });

  it('shows inline date_range_invalid when to < from', async () => {
    renderDialog();
    await screen.findByText('W40 · Oct 3 – Oct 9, 2026');
    await userEvent.click(screen.getByText(/advanced options/i));
    await userEvent.type(screen.getByLabelText('Window'), '2026-10-20 – 2026-10-05');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    expect(
      (await screen.findAllByText(/End date must be on or after start date/i)).length,
    ).toBeGreaterThan(0);
  });

  it('submits populate options from the advanced section', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const bodies = capturePost();
    renderDialog({ onClose });
    await screen.findByText('W40 · Oct 3 – Oct 9, 2026');

    await user.click(screen.getByText(/advanced options/i));
    const weeks = screen.getByLabelText(/OLD depth \(weeks\)/i);
    await user.clear(weeks);
    await user.type(weeks, '2');
    await user.click(screen.getByRole('button', { name: /create/i }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(bodies[0]).toMatchObject({ old_offset_weeks: 2, include_disliked_labels: true });
  });

  it('submits all classification flags on by default without opening advanced', async () => {
    const onClose = vi.fn();
    const bodies = capturePost();
    renderDialog({ onClose });
    await screen.findByText('W40 · Oct 3 – Oct 9, 2026');
    await userEvent.click(screen.getByRole('button', { name: /create/i }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(bodies[0]).toMatchObject({
      include_disliked_labels: true,
      include_disliked_artists: true,
      compilations_to_not: true,
      include_favorites: true,
    });
  });

  it('shows yellow toast on 503 and closes modal', async () => {
    const onClose = vi.fn();
    server.use(
      http.post('http://localhost/triage/blocks', () =>
        HttpResponse.json({ message: 'Service Unavailable' }, { status: 503 }),
      ),
    );
    renderDialog({ onClose });
    await screen.findByText('W40 · Oct 3 – Oct 9, 2026');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(
      await screen.findByText(/Creation is taking longer than usual/i),
    ).toBeInTheDocument();
  });
});
