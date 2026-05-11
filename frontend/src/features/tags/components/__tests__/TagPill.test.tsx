import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { TagPill } from '../TagPill';

function W({ children }: { children: React.ReactNode }) {
  return <MantineProvider>{children}</MantineProvider>;
}

describe('TagPill', () => {
  it('renders the tag name', () => {
    render(
      <W>
        <TagPill name="Vocal" color="#ff8800" />
      </W>,
    );
    expect(screen.getByText('Vocal')).toBeInTheDocument();
  });

  it('uses the colour as background when provided', () => {
    render(
      <W>
        <TagPill name="Vocal" color="#ff8800" data-testid="pill" />
      </W>,
    );
    const el = screen.getByTestId('pill');
    expect(el.style.backgroundColor).toBe('rgb(255, 136, 0)');
  });

  it('falls back to a neutral outline when colour is null', () => {
    render(
      <W>
        <TagPill name="Vocal" color={null} data-testid="pill" />
      </W>,
    );
    const el = screen.getByTestId('pill');
    expect(el.style.backgroundColor).toBe('transparent');
    expect(el.style.borderStyle).toBe('solid');
  });
});
