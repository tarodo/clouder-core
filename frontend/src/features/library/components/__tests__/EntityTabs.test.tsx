import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { MantineProvider } from '@mantine/core';
import i18n from '../../../../i18n';
import { EntityTabs } from '../EntityTabs';

function renderWith(active: 'labels' | 'artists') {
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <MemoryRouter><EntityTabs active={active} styleId="dnb" /></MemoryRouter>
      </I18nextProvider>
    </MantineProvider>
  );
}

describe('EntityTabs', () => {
  it('renders Labels and Artists tabs', () => {
    renderWith('labels');
    expect(screen.getByText('Labels')).toBeInTheDocument();
    expect(screen.getByText('Artists')).toBeInTheDocument();
  });
  it('artists tab is enabled (not data-disabled)', () => {
    renderWith('labels');
    const artistsTab = screen.getByText('Artists').closest('button');
    expect(artistsTab).not.toHaveAttribute('data-disabled');
  });
  it('marks active tab as selected', () => {
    renderWith('artists');
    const artistsTab = screen.getByText('Artists').closest('button');
    expect(artistsTab).toHaveAttribute('data-active');
  });
});
