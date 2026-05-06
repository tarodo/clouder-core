import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../test/theme';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../../i18n';
import type { ReactElement } from 'react';
import { LeaveContextDialog } from '../LeaveContextDialog';

interface TestRouteFn {
  (): ReactElement;
}

function buildRouter(initial: string, renderFn: TestRouteFn) {
  return createMemoryRouter([{ path: '*', element: renderFn() }], {
    initialEntries: [initial],
  });
}

function wrap(router: ReturnType<typeof buildRouter>) {
  return (
    <MantineProvider theme={testTheme}>
      <I18nextProvider i18n={i18n}>
        <RouterProvider router={router} />
      </I18nextProvider>
    </MantineProvider>
  );
}

describe('LeaveContextDialog', () => {
  it('does not block when active=false', async () => {
    const onConfirm = vi.fn();
    const router = buildRouter('/curate/x/A/U', () => (
      <>
        <div>route</div>
        <LeaveContextDialog
          active={false}
          currentPath="/curate/x/A/U"
          onConfirm={onConfirm}
        />
      </>
    ));
    render(wrap(router));
    await router.navigate('/curate/x/B/U');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('blocks navigation between curate sessions when active=true', async () => {
    const onConfirm = vi.fn();
    const router = buildRouter('/curate/x/A/U', () => (
      <>
        <div>route</div>
        <LeaveContextDialog
          active={true}
          currentPath={'/curate/x/A/U'}
          onConfirm={onConfirm}
        />
      </>
    ));
    render(wrap(router));
    void router.navigate('/curate/x/B/U');
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
  });

  it('cancel resets blocker, stays on current path', async () => {
    const onConfirm = vi.fn();
    const router = buildRouter('/curate/x/A/U', () => (
      <>
        <div>route</div>
        <LeaveContextDialog
          active={true}
          currentPath={'/curate/x/A/U'}
          onConfirm={onConfirm}
        />
      </>
    ));
    render(wrap(router));
    void router.navigate('/curate/x/B/U');
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /Нет, остаться/i }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('confirm calls onConfirm + proceeds', async () => {
    const onConfirm = vi.fn();
    const router = buildRouter('/curate/x/A/U', () => (
      <>
        <div>route</div>
        <LeaveContextDialog
          active={true}
          currentPath={'/curate/x/A/U'}
          onConfirm={onConfirm}
        />
      </>
    ));
    render(wrap(router));
    void router.navigate('/curate/x/B/U');
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /Да, новый блок/i }));
    expect(onConfirm).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('does not block when target is not a PlayerCard route', async () => {
    const router = buildRouter('/curate/x/A/U', () => (
      <>
        <div>route</div>
        <LeaveContextDialog
          active={true}
          currentPath={'/curate/x/A/U'}
          onConfirm={vi.fn()}
        />
      </>
    ));
    render(wrap(router));
    await router.navigate('/tracks');
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
