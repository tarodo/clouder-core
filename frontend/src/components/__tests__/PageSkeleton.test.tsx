import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { PageSkeleton } from '../PageSkeleton';

const wrap = (ui: React.ReactNode) => render(<MantineProvider>{ui}</MantineProvider>);

describe('PageSkeleton', () => {
  it('renders gray rows, marked busy, with no spinner', () => {
    wrap(<PageSkeleton rows={4} />);
    const root = screen.getByTestId('page-skeleton');
    expect(root.getAttribute('aria-busy')).toBe('true');
    expect(root.querySelectorAll('.mantine-Skeleton-root').length).toBe(2 + 4); // header row + rows
    expect(document.querySelector('.mantine-Loader-root')).toBeNull();
  });

  it('renders rows only with header="none" and lays them out as a grid with cols', () => {
    wrap(<PageSkeleton header="none" cols={3} rows={6} />);
    const root = screen.getByTestId('page-skeleton');
    expect(root.querySelectorAll('.mantine-Skeleton-root').length).toBe(6);
    expect(root.querySelector('.mantine-SimpleGrid-root')).not.toBeNull();
  });

  it('adds breadcrumbs, hero header and the desktop side panel when asked', () => {
    wrap(<PageSkeleton breadcrumbs header="hero" aside rows={2} />);
    // breadcrumbs 1 + hero (cover + 3 lines) 4 + aside 1 + rows 2
    expect(screen.getByTestId('page-skeleton').querySelectorAll('.mantine-Skeleton-root').length).toBe(8);
  });
});
