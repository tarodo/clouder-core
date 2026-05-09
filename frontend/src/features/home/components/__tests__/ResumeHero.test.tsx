import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../../../i18n';
import { ResumeHero } from '../ResumeHero';
import type { TriageBlockSummary } from '../../../triage/hooks/useTriageBlocksByStyle';

function wrap(node: React.ReactNode) {
  return (
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <MemoryRouter>{node}</MemoryRouter>
      </I18nextProvider>
    </MantineProvider>
  );
}

const block: TriageBlockSummary = {
  id: 'b1', style_id: 's1', style_name: 'House', name: '2026-W18',
  date_from: '2026-05-04', date_to: '2026-05-10', status: 'IN_PROGRESS',
  created_at: '2026-05-04T00:00:00Z', updated_at: '2026-05-08T00:00:00Z',
  finalized_at: null, track_count: 42,
};

describe('ResumeHero', () => {
  it('renders the curate state with a deep-link to /curate/:style/:block/:bucket', () => {
    render(
      wrap(
        <ResumeHero
          target={{
            kind: 'curate',
            session: { styleId: 's1', blockId: 'b1', bucketId: 'bk1' },
            block,
          }}
        />,
      ),
    );
    const link = screen.getByRole('link', { name: /continue/i });
    expect(link.getAttribute('href')).toBe('/curate/s1/b1/bk1');
  });

  it('renders the triage state with a deep-link to /triage/:style/:id', () => {
    render(wrap(<ResumeHero target={{ kind: 'triage', block }} />));
    const link = screen.getByRole('link', { name: /open block/i });
    expect(link.getAttribute('href')).toBe('/triage/s1/b1');
  });

  it('renders the empty state with the create CTA', () => {
    render(wrap(<ResumeHero target={{ kind: 'empty' }} />));
    const link = screen.getByRole('link', { name: /create first/i });
    expect(link.getAttribute('href')).toBe('/triage?create=1');
  });
});
