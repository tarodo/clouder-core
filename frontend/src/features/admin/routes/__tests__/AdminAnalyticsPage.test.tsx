import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { AdminAnalyticsPage } from '../AdminAnalyticsPage';

const calls = vi.hoisted(() => ({ listening: [] as string[], funnel: [] as string[] }));

vi.mock('../../hooks/useUsers', () => ({
  useUsers: () => ({
    data: { users: [{ id: 'u1', display_name: 'Alice' }, { id: 'u2', display_name: null }] },
    isLoading: false,
  }),
}));

vi.mock('../../../analytics/hooks/useAnalytics', () => ({
  useListening: (userId: string) => {
    calls.listening.push(userId);
    return { data: undefined, isLoading: true, isError: false };
  },
  useFunnel: (userId: string) => {
    calls.funnel.push(userId);
    return { data: undefined, isLoading: true, isError: false };
  },
}));

describe('AdminAnalyticsPage', () => {
  it('defaults to the caller, then scopes both cards to the picked user', async () => {
    render(
      <MantineProvider>
        <AdminAnalyticsPage />
      </MantineProvider>,
    );
    expect(calls.listening.at(-1)).toBe('');
    await userEvent.click(screen.getByRole('combobox', { name: 'User' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Alice' }));
    expect(calls.listening.at(-1)).toBe('u1');
    expect(calls.funnel.at(-1)).toBe('u1');
  });
});
