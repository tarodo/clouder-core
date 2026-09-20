/**
 * Browser test — keyboard-driven dnd-kit reorder. jsdom applies no stylesheets
 * and no real layout, so `closestCenter` collision detection and dnd-kit's
 * keyboard coordinate getter (both of which need real geometry) can only be
 * exercised here.
 *
 * No *.browser.test.tsx in this repo wires up msw for network mocking — there
 * is no mockServiceWorker.js, and msw/node's setupServer (used by the jsdom
 * suite via test/setup.ts) depends on Node's http internals that don't exist
 * inside the Playwright-driven browser page. The established convention for a
 * network-backed browser test (see PublishYtMusicButton.browser.test.tsx) is
 * to replace `api/client` directly with vi.mock, so that's what this does
 * instead of the msw setup a plain jsdom test would use.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import { MyStylesSection } from '../MyStylesSection';

// vi.mock factories are hoisted above imports; vi.hoisted() gives the factory
// a reference that exists before that hoist, avoiding a TDZ read on a
// module-scope `let`.
const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));

vi.mock('../../../../api/client', () => ({ api: apiMock }));

const catalog = {
  items: [
    { id: 's1', name: 'Drum & Bass', selected: true, position: 0 },
    { id: 's2', name: 'House', selected: true, position: 1 },
  ],
  total: 2,
  limit: 200,
  offset: 0,
};

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <MyStylesSection />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('MyStylesSection (browser)', () => {
  it('keyboard reorder sends the swapped order', async () => {
    let putBody: { style_ids: string[] } | null = null;
    apiMock.mockReset();
    apiMock.mockImplementation(
      async (path: string, init?: { method?: string; body?: string }) => {
        if (path.startsWith('/styles')) return catalog;
        if (path === '/me/styles' && init?.method === 'PUT') {
          putBody = JSON.parse(init.body ?? '{}') as { style_ids: string[] };
          return undefined;
        }
        throw new Error(`unexpected api call: ${path} ${init?.method ?? 'GET'}`);
      },
    );

    renderSection();

    await screen.findByText('Drum & Bass');
    const handles = screen.getAllByRole('button', { name: /Reorder/i });
    // noUncheckedIndexedAccess: handles[0] types as `HTMLElement | undefined`;
    // guard instead of asserting so a missing handle fails loudly, not silently.
    const firstHandle = handles[0];
    if (!firstHandle) throw new Error('expected at least one drag handle');

    firstHandle.focus();
    await userEvent.keyboard('{ }'); // pick up
    await userEvent.keyboard('{ArrowDown}'); // move below "House"
    await userEvent.keyboard('{ }'); // drop

    await waitFor(() => expect(putBody).toEqual({ style_ids: ['s2', 's1'] }));
  });
});
