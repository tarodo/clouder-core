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

  it('renders a soft tint background derived from the colour', () => {
    render(
      <W>
        <TagPill name="Vocal" color="#ff8800" data-testid="pill" />
      </W>,
    );
    const el = screen.getByTestId('pill');
    expect(el.style.backgroundColor).toBe('rgba(255, 136, 0, 0.13)');
    // fg darkened: 255*.55=140, 136*.55=75, 0 → #8c4b00
    expect(el.style.color).toBe('rgb(140, 75, 0)');
  });

  it('falls back to a neutral grey tint when colour is null', () => {
    render(
      <W>
        <TagPill name="Vocal" color={null} data-testid="pill" />
      </W>,
    );
    const el = screen.getByTestId('pill');
    expect(el.style.backgroundColor).toBe('rgba(100, 116, 139, 0.12)');
    expect(el.style.color).toBe('rgb(71, 85, 105)'); // #475569
  });

  it('renders mono, centered, with a 2-char min-width for uniform short pills', () => {
    render(
      <W>
        <TagPill name="A" color="#ff8800" data-testid="pill" />
      </W>,
    );
    const el = screen.getByTestId('pill');
    expect(el.style.fontFamily).toBe('var(--font-mono)');
    expect(el.style.minWidth).toBe('calc(2ch + 18px)');
    expect(el.style.justifyContent).toBe('center');
  });
});
