import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, test } from 'vitest';
import { page } from 'vitest/browser';
import '../../../../i18n';
import { AdminLayout } from '../AdminLayout';

function renderAt(path: string) {
  return render(
    <MantineProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/admin/*" element={<AdminLayout />} />
        </Routes>
      </MemoryRouter>
    </MantineProvider>,
  );
}

describe('AdminLayout tabs on a phone', () => {
  test('stay one row', async () => {
    await page.viewport(390, 800);
    renderAt('/admin/coverage');
    const tops = screen.getAllByRole('tab').map((t) => t.getBoundingClientRect().top);
    expect(new Set(tops).size).toBe(1);
  });

  test('draw the baseline under every tab', async () => {
    await page.viewport(390, 800);
    renderAt('/admin/coverage');
    // The list's ::before baseline spans the list box: the list must not scroll inside itself.
    const list = screen.getByRole('tablist');
    expect(list.scrollWidth).toBeLessThanOrEqual(list.clientWidth);
  });

  test('scroll the active tab into view', async () => {
    await page.viewport(390, 800);
    renderAt('/admin/analytics');
    const tab = screen.getByRole('tab', { name: 'Analytics' });
    const list = screen.getByRole('tablist').getBoundingClientRect();
    await expect.poll(() => tab.getBoundingClientRect().right).toBeLessThanOrEqual(list.right + 1);
  });
});
