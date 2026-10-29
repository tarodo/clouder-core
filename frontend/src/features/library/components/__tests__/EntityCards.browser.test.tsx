import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { expect, test, vi } from 'vitest';
import '../../../../i18n';
import { clouderTheme } from '../../../../theme';
import { labelInfoKey } from '../../hooks/useLabelInfo';
import { ArtistsPanel } from '../ArtistsPanel';
import { LabelTile } from '../LabelTile';

// Repo convention for browser tests: replace api/client (no msw); data is seeded into the cache.
vi.mock('../../../../api/client', () => ({ api: vi.fn(() => new Promise(() => {})) }));

const stats = { tracks: 412, in_categories: 9, in_playlists: 3 };

function renderPanel(width = 320) {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  qc.setQueryData(labelInfoKey('l1'), { label_name: 'Exit Strategy', my_preference: null, stats });
  qc.setQueryData(['artistInfo', 'a1'], { artist_name: 'Ivory (IT)', my_preference: 'liked', stats });
  qc.setQueryData(['artistInfo', 'a2'], {
    artist_name: 'Julia Linkogel',
    my_preference: null,
    stats,
    country: 'DE',
    summary: 'A singer and producer from Cologne.',
  });
  return render(
    <MantineProvider theme={clouderTheme}>
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <div style={{ width }} data-testid="panel">
            <LabelTile labelId="l1" labelName="Exit Strategy" />
            <ArtistsPanel
              artists={[
                { id: 'a1', name: 'Ivory (IT)', role: 'main' },
                { id: 'a2', name: 'Julia Linkogel', role: 'main' },
              ]}
            />
          </div>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

test('the label and every artist card share one look: name type, buttons, width', () => {
  renderPanel();
  const names = ['Exit Strategy', 'Ivory (IT)', 'Julia Linkogel'].map((n) =>
    screen.getByRole('link', { name: n }),
  );
  const fonts = names.map((el) => {
    const s = getComputedStyle(el);
    return [s.fontSize, s.fontWeight, s.fontFamily];
  });
  expect(new Set(fonts.map(String)).size).toBe(1);

  const cards = names.map((el) => el.closest('[data-entity]')!);
  const widths = cards.map((c) => Math.round(c.getBoundingClientRect().width));
  expect(new Set(widths).size).toBe(1);

  // like / dislike sit on the caption line, flush right, in every card
  const dislikes = cards.map((c) => c.querySelectorAll('button')[1]!);
  const rights = dislikes.map((b) => Math.round(b.getBoundingClientRect().right));
  expect(new Set(rights).size).toBe(1);
  const tops = cards.map((c, i) =>
    Math.round(dislikes[i]!.getBoundingClientRect().top - c.getBoundingClientRect().top),
  );
  expect(new Set(tops).size).toBe(1);
});

test('in a player panel the cards are as wide as the player (442px)', () => {
  renderPanel(442);
  const cards = [...document.querySelectorAll('[data-entity]')];
  expect(cards).toHaveLength(3);
  for (const card of cards) expect(card.getBoundingClientRect().width).toBe(442);
});
