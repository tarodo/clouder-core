import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CategoryFormDialog } from '../CategoryFormDialog';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </MantineProvider>
  );
}

describe('CategoryFormDialog', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (q: string) => ({
        matches: false,
        media: q,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }),
    });
  });

  it('shows inline error on empty submit', async () => {
    const onSubmit = vi.fn();
    render(
      <Wrapper>
        <CategoryFormDialog
          mode="create"
          opened
          initialName=""
          submitting={false}
          onClose={() => {}}
          onSubmit={onSubmit}
        />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /create/i }));
    expect(await screen.findByText(/name is required/i)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('submits valid name', async () => {
    const onSubmit = vi.fn();
    render(
      <Wrapper>
        <CategoryFormDialog
          mode="create"
          opened
          initialName=""
          submitting={false}
          onClose={() => {}}
          onSubmit={onSubmit}
        />
      </Wrapper>,
    );
    await userEvent.type(screen.getByRole('textbox', { name: /name/i }), 'Tech House');
    await userEvent.click(screen.getByRole('button', { name: /create/i }));
    expect(onSubmit).toHaveBeenCalledWith({ name: 'Tech House' });
  });

  it('shows server error from prop', async () => {
    render(
      <Wrapper>
        <CategoryFormDialog
          mode="rename"
          opened
          initialName="Old"
          submitting={false}
          onClose={() => {}}
          onSubmit={() => {}}
          serverError="A category with this name already exists in this style."
        />
      </Wrapper>,
    );
    expect(screen.getByText(/already exists/i)).toBeInTheDocument();
  });
});
