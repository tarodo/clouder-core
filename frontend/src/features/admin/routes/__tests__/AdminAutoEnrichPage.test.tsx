import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AdminAutoEnrichPage } from '../AdminAutoEnrichPage';

// i18n is initialized globally in src/test/setup.ts, so useTranslation() returns
// real translated values here — no I18nextProvider wrapper needed.

const mockSave = vi.fn().mockResolvedValue(undefined);
// `data` is built ONCE inside the factory closure so the hook returns a stable
// reference across renders — matching real TanStack Query. A fresh object per
// call would change the `[query.data]` effect dep every render and loop forever.
vi.mock('../../hooks/useAutoEnrichConfig', () => {
  const data = {
    config: {
      enabled: false, vendors: [], models: {},
      prompt_slug: null, prompt_version: null,
      merge_vendor: 'deepseek', merge_model: null,
    },
    options: {
      vendors: ['gemini', 'openai', 'tavily_deepseek'],
      prompt_versions: [{ slug: 'label_v3', version: 'v1', is_default: true }],
      default_models: { gemini: 'g', openai: 'o', tavily_deepseek: 'd' },
      merge: { vendor: 'deepseek', default_model: 'deepseek-v4-flash' },
    },
  };
  return {
    useAutoEnrichConfig: () => ({ data, isLoading: false, isError: false }),
  };
});
vi.mock('../../hooks/useSaveAutoEnrichConfig', () => ({
  useSaveAutoEnrichConfig: () => ({ mutateAsync: mockSave, isPending: false }),
}));

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <AdminAutoEnrichPage />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('AdminAutoEnrichPage', () => {
  beforeEach(() => mockSave.mockClear());

  it('shows three tabs with artists/tracks disabled', () => {
    renderPage();
    expect(screen.getByRole('tab', { name: /labels/i })).toBeEnabled();
    expect(screen.getByRole('tab', { name: /artists/i })).toBeDisabled();
    expect(screen.getByRole('tab', { name: /tracks/i })).toBeDisabled();
  });

  it('saves config on Save click', async () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
    expect(mockSave.mock.calls[0]?.[0]).toMatchObject({ enabled: false });
  });
});
