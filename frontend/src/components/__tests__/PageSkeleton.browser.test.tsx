import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { PageSkeleton } from '../PageSkeleton';

describe.each([375, 1200])('PageSkeleton at %ipx', (width) => {
  test.each([
    ['category detail', { breadcrumbs: true, aside: true }],
    ['playlist detail', { breadcrumbs: true, header: 'hero' as const }],
    ['list', {}],
  ])('%s fits the width', (_, props) => {
    render(
      <MantineProvider>
        <div style={{ width }}>
          <PageSkeleton {...props} />
        </div>
      </MantineProvider>,
    );
    const root = screen.getByTestId('page-skeleton');
    expect(root.scrollWidth).toBeLessThanOrEqual(root.clientWidth);
  });
});
