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

const server = setupServer();
beforeEach(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  server.close();
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

describe('CreateTriageBlockDialog', () => {
  it('renders fields', () => {
    renderDialog();
    expect(screen.getByLabelText('Name')).toBeInTheDocument();
    expect(screen.getByLabelText('Window')).toBeInTheDocument();
  });

  it('submits a happy path POST', async () => {
    const onClose = vi.fn();
    server.use(
      http.post('http://localhost/triage/blocks', async ({ request }) => {
        const body = (await request.json()) as Record<string, string>;
        expect(body.style_id).toBe('s1');
        expect(body.name).toBe('House W17');
        expect(body.date_from).toBe('2026-04-20');
        expect(body.date_to).toBe('2026-04-26');
        return HttpResponse.json(
          {
            id: 'b1',
            style_id: 's1',
            style_name: 'House',
            name: 'House W17',
            date_from: '2026-04-20',
            date_to: '2026-04-26',
            status: 'IN_PROGRESS',
            created_at: 'now',
            updated_at: 'now',
            finalized_at: null,
            buckets: [],
          },
          { status: 201 },
        );
      }),
    );

    renderDialog({ onClose });
    const dateInput = screen.getByLabelText('Window');
    await userEvent.click(dateInput);
    await userEvent.type(dateInput, '2026-04-20 – 2026-04-26');
    await waitFor(() => {
      expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('House W17');
    });
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('preserves user-edited name across date changes', async () => {
    server.use(
      http.post('http://localhost/triage/blocks', () => HttpResponse.json({}, { status: 201 })),
    );
    renderDialog();
    const nameInput = screen.getByLabelText('Name') as HTMLInputElement;
    await userEvent.type(nameInput, 'My Custom');
    const dateInput = screen.getByLabelText('Window');
    await userEvent.type(dateInput, '2026-04-20 – 2026-04-26');
    await waitFor(() => expect(nameInput.value).toBe('My Custom'));
  });

  it('shows inline date_range_invalid when to < from', async () => {
    renderDialog();
    const dateInput = screen.getByLabelText('Window');
    await userEvent.type(dateInput, '2026-04-26 – 2026-04-20');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    expect(await screen.findByText(/End date must be on or after start date/i)).toBeInTheDocument();
  });

  it('shows yellow toast on 503 and closes modal', async () => {
    const onClose = vi.fn();
    server.use(
      http.post('http://localhost/triage/blocks', () =>
        HttpResponse.json({ message: 'Service Unavailable' }, { status: 503 }),
      ),
    );
    renderDialog({ onClose });
    await userEvent.type(
      screen.getByLabelText('Window'),
      '2026-04-20 – 2026-04-26',
    );
    await waitFor(() =>
      expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('House W17'),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(
      await screen.findByText(/Creation is taking longer than usual/i),
    ).toBeInTheDocument();
  });
});
