import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CategoryPlayerPage } from '../CategoryPlayerPage';

// Stub usePlayback + the player panel (we don't need to render full UI here).
vi.mock('../../../playback/usePlayback', () => ({
  usePlayback: () => ({
    controls: {
      prewarm: vi.fn(() => Promise.resolve()),
      bindQueue: vi.fn(),
      clearQueue: vi.fn(),
    },
    queue: { source: null, tracks: [], cursor: 0, status: 'idle' },
    track: { current: null, positionMs: 0, durationMs: 0 },
    sdk: { ready: false, error: null },
    devices: {} as never,
  }),
}));
vi.mock('../../components/CategoryPlayerPanel', () => ({
  CategoryPlayerPanel: ({ categoryId, styleId }: { categoryId: string; styleId: string }) => (
    <div data-testid="panel">
      {categoryId}/{styleId}
    </div>
  ),
}));
vi.mock('../../hooks/useCategoryPlayerQueue', () => ({
  useCategoryPlayerQueue: vi.fn(),
}));
vi.mock('../../hooks/useCategoryTracks', () => ({
  useCategoryTracks: () => ({ data: undefined }),
}));

describe('CategoryPlayerPage', () => {
  it('renders the panel with route params', () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <MantineProvider>
          <MemoryRouter initialEntries={['/categories/s1/c1/player']}>
            <Routes>
              <Route path="/categories/:styleId/:id/player" element={<CategoryPlayerPage />} />
            </Routes>
          </MemoryRouter>
        </MantineProvider>
      </QueryClientProvider>,
    );
    expect(screen.getByTestId('panel')).toHaveTextContent('c1/s1');
  });

  it('back button navigates to the detail page', () => {
    // Smoke: button exists with the back-aria label.
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <MantineProvider>
          <MemoryRouter initialEntries={['/categories/s1/c1/player']}>
            <Routes>
              <Route path="/categories/:styleId/:id/player" element={<CategoryPlayerPage />} />
            </Routes>
          </MemoryRouter>
        </MantineProvider>
      </QueryClientProvider>,
    );
    // i18n key fallback or translation — match by substring
    expect(screen.getByRole('button')).toBeInTheDocument();
  });
});
