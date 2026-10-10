import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, within } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { page } from '@vitest/browser/context';
import '../../../../i18n';
import { SpotifySearchStatus } from '../SpotifySearchStatus';

function seeded() {
  const qc = new QueryClient();
  qc.setQueryData(['admin', 'spotifySearchStatus'], {
    status: 'running', paused_until: null,
    queue: { waiting_messages: 0, in_flight: 1, delayed: 0 },
    tracks: { waiting: 4120, not_found: 3051, searched_last_10_min: 600 },
  });
  return qc;
}

function mount() {
  return render(
    <QueryClientProvider client={seeded()}>
      <MantineProvider>
        <SpotifySearchStatus />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('SpotifySearchStatus layout', () => {
  test('the three numbers sit in one row on desktop', async () => {
    await page.viewport(1280, 900);
    const ui = within(mount().container);
    const top = (text: string) => ui.getByText(text).getBoundingClientRect().top;
    await ui.findByText('4,120');
    expect(top('600')).toBeCloseTo(top('4,120'), 0);
    expect(top('3,051')).toBeCloseTo(top('4,120'), 0);
  });

  test('stacks on a phone without horizontal overflow', async () => {
    await page.viewport(375, 800);
    const { container } = mount();
    const ui = within(container);
    await ui.findByText('4,120');
    expect(ui.getByText('3,051').getBoundingClientRect().top).toBeGreaterThan(
      ui.getByText('4,120').getBoundingClientRect().top,
    );
    expect(container.scrollWidth).toBeLessThanOrEqual(375);
  });
});
