import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../test/setup';
import { tokenStore } from '../../auth/tokenStore';
import { StyleSelector } from '../StyleSelector';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </MantineProvider>
  );
}

describe('StyleSelector', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('renders styles and fires onChange', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [
            { id: 's1', name: 'House' },
            { id: 's2', name: 'Tech House' },
          ],
          total: 2,
          limit: 200,
          offset: 0,
        }),
      ),
    );
    const onChange = vi.fn();
    render(
      <Wrapper>
        <StyleSelector value="s1" onChange={onChange} />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByDisplayValue('House')).toBeInTheDocument());
    await userEvent.click(screen.getByDisplayValue('House'));
    await userEvent.click(screen.getByText('Tech House'));
    expect(onChange).toHaveBeenCalledWith('s2');
  });
});
