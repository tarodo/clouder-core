import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { testTheme } from '../../../../test/theme';

// Mantine's DatePickerInput renders as a button-like trigger that opens a
// popover calendar — userEvent.type cannot drive it under jsdom. Replace it
// with a plain text input that parses the "YYYY-MM-DD – YYYY-MM-DD" string
// and forwards a [string, string] tuple, matching this repo's Mantine 9
// range-value convention (see CreateTriageBlockDialog.tsx / .test.tsx).
vi.mock('@mantine/dates', async () => {
  const React = await import('react');
  type Props = {
    label?: string;
    onChange?: (value: [string | null, string | null]) => void;
  };
  const DatePickerInput = ({ label, onChange }: Props) => {
    const [text, setText] = React.useState('');
    return (
      <label>
        {label}
        <input
          type="text"
          value={text}
          onChange={(e) => {
            const raw = e.target.value;
            setText(raw);
            const parts = raw.split(' – ');
            if (parts.length === 2 && parts[0] && parts[1]) {
              onChange?.([parts[0].trim(), parts[1].trim()]);
              return;
            }
            onChange?.([null, null]);
          }}
        />
      </label>
    );
  };
  return { DatePickerInput };
});

import { SpotifyNotFoundTable } from '../SpotifyNotFoundTable';

function ui() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <ModalsProvider>
          <Notifications />
          <SpotifyNotFoundTable />
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>
  );
}

const LIST = {
  items: [
    { track_id: 't1', title: 'Lost Groove', artists: ['DJ A'], isrc: 'ZZ1' },
  ],
  total: 1,
  limit: 50,
  offset: 0,
};

describe('SpotifyNotFoundTable retry', () => {
  it('disables the retry button until a full date range is picked', async () => {
    server.use(
      http.get('http://localhost/tracks/spotify-not-found', () =>
        HttpResponse.json(LIST),
      ),
    );
    render(ui());
    const button = await screen.findByRole('button', {
      name: 'Retry Spotify search',
    });
    expect(button).toBeDisabled();
  });

  it('confirms and posts the retry, then shows the queued toast', async () => {
    let posted: unknown = null;
    server.use(
      http.get('http://localhost/tracks/spotify-not-found', () =>
        HttpResponse.json(LIST),
      ),
      http.post(
        'http://localhost/admin/spotify/retry-not-found',
        async ({ request }) => {
          posted = await request.json();
          return HttpResponse.json({ queued_count: 3 });
        },
      ),
    );
    render(ui());
    await screen.findByText('Lost Groove');

    // Type the range into the (mocked) DatePickerInput.
    const rangeInput = screen.getByLabelText('Release date range');
    await userEvent.click(rangeInput);
    await userEvent.type(rangeInput, '2026-04-01 – 2026-04-15');

    const button = screen.getByRole('button', { name: 'Retry Spotify search' });
    expect(button).toBeEnabled();
    await userEvent.click(button);

    await userEvent.click(await screen.findByRole('button', { name: 'Retry' }));

    expect(await screen.findByText('Queued 3 tracks')).toBeInTheDocument();
    expect(posted).toMatchObject({
      publish_date_from: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      publish_date_to: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
    });
  });
});
