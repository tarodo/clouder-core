import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CoverPicker } from '../CoverPicker';
import { testTheme } from '../../../../test/theme';

vi.mock('../../hooks/useUploadCover', () => ({
  useUploadCover: () => ({ mutateAsync: vi.fn(), isPending: false }),
  MAX_COVER_BYTES: 256 * 1024,
}));

vi.mock('../../hooks/useClearCover', () => ({
  useClearCover: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <ModalsProvider>
          {children}
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>
  );
}

describe('CoverPicker', () => {
  it('has no visible "Replace cover" button — avatar is the click target', () => {
    const { container } = render(
      <Wrapper>
        <CoverPicker playlistId="p1" coverUrl={null} />
      </Wrapper>,
    );
    // The old explicit <Button>Replace cover</Button> is gone; the clickable
    // avatar (UnstyledButton) carries the aria-label but is not a visible button.
    // Verify there is exactly one button (the avatar wrapper) — no extra Replace button.
    const buttons = container.querySelectorAll('button');
    // Only the avatar UnstyledButton should be present (no separate "Replace" button)
    expect(buttons.length).toBe(1);
    // file input must still exist (inside FileButton)
    expect(container.querySelector('input[type="file"]')).toBeTruthy();
  });

  it('shows limits help text inside the empty placeholder', () => {
    render(
      <Wrapper>
        <CoverPicker playlistId="p1" coverUrl={null} />
      </Wrapper>,
    );
    // help_text key value
    expect(screen.getByText(/jpeg or png/i)).toBeInTheDocument();
    // upload_hint key value
    expect(screen.getByText(/click to upload/i)).toBeInTheDocument();
  });

  it('does not show the remove trash button when coverUrl is null', () => {
    render(
      <Wrapper>
        <CoverPicker playlistId="p1" coverUrl={null} />
      </Wrapper>,
    );
    expect(screen.queryByRole('button', { name: /remove cover/i })).toBeNull();
  });

  it('shows the remove trash button when coverUrl is set', () => {
    render(
      <Wrapper>
        <CoverPicker playlistId="p1" coverUrl="https://example.com/cover.jpg" />
      </Wrapper>,
    );
    expect(screen.getByRole('button', { name: /remove cover/i })).toBeInTheDocument();
  });
});
