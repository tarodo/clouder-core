import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../../../i18n';
import { CountersGrid } from '../CountersGrid';

function wrap(node: React.ReactNode) {
  return (
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <MemoryRouter>{node}</MemoryRouter>
      </I18nextProvider>
    </MantineProvider>
  );
}

describe('CountersGrid', () => {
  it('renders both counters with values and links to /triage', () => {
    render(wrap(<CountersGrid awaitingTriage={312} activeBlocks={7} />));
    expect(screen.getByText('312')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(2);
    expect(links[0]?.getAttribute('href')).toBe('/triage');
    expect(links[1]?.getAttribute('href')).toBe('/triage');
  });
});
