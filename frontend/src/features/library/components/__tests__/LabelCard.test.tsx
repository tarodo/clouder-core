import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { MantineProvider } from '@mantine/core';
import i18n from '../../../../i18n';
import { LabelCard } from '../LabelCard';

const COMPLETED = {
  id: 'l1', name: 'Fokuz', style: 'dnb', status: 'completed' as const,
  track_count: 142,
  info: {
    tagline: 'soulful d&b', country: 'NL',
    primary_styles: ['liquid', 'jazzstep'], activity: 'steady' as const,
    updated_at: '2026-05-19T00:00:00Z',
  },
};

const PENDING = {
  id: 'l2', name: 'Unknown', style: 'dnb', status: 'none' as const,
  track_count: 0, info: null,
};

function renderCard(item: typeof COMPLETED | typeof PENDING) {
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <MemoryRouter><LabelCard item={item} /></MemoryRouter>
      </I18nextProvider>
    </MantineProvider>
  );
}

describe('LabelCard', () => {
  it('renders tagline + styles for completed labels', () => {
    renderCard(COMPLETED);
    expect(screen.getByText('Fokuz')).toBeInTheDocument();
    expect(screen.getByText('soulful d&b')).toBeInTheDocument();
    expect(screen.getByText('liquid')).toBeInTheDocument();
  });
  it('renders pending placeholder when no info', () => {
    renderCard(PENDING);
    expect(screen.getByText('Info pending')).toBeInTheDocument();
  });
});
