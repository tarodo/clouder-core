import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { ColorSwatchPicker } from '../ColorSwatchPicker';
import { TAG_PALETTE } from '../../lib/tagPalette';

function W({ children }: { children: React.ReactNode }) {
  return <MantineProvider>{children}</MantineProvider>;
}

describe('ColorSwatchPicker', () => {
  it('renders all 12 palette swatches plus the clear button', () => {
    render(
      <W>
        <ColorSwatchPicker value={null} onChange={() => {}} />
      </W>,
    );
    for (const c of TAG_PALETTE) {
      expect(screen.getByRole('button', { name: `colour ${c}` })).toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: /no colour/i })).toBeInTheDocument();
  });

  it('marks the active swatch with aria-pressed=true', () => {
    render(
      <W>
        <ColorSwatchPicker value={TAG_PALETTE[2]} onChange={() => {}} />
      </W>,
    );
    expect(
      screen.getByRole('button', { name: `colour ${TAG_PALETTE[2]}` }),
    ).toHaveAttribute('aria-pressed', 'true');
  });

  it('emits the picked colour', async () => {
    const onChange = vi.fn();
    render(
      <W>
        <ColorSwatchPicker value={null} onChange={onChange} />
      </W>,
    );
    await userEvent.click(
      screen.getByRole('button', { name: `colour ${TAG_PALETTE[0]}` }),
    );
    expect(onChange).toHaveBeenCalledWith(TAG_PALETTE[0]);
  });

  it('emits null when "no colour" pressed', async () => {
    const onChange = vi.fn();
    render(
      <W>
        <ColorSwatchPicker value={TAG_PALETTE[0]} onChange={onChange} />
      </W>,
    );
    await userEvent.click(screen.getByRole('button', { name: /no colour/i }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
