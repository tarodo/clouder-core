/**
 * Browser-mode smoke for YtMusicBadge: verifies link rendering for matched
 * status and absence of link for pending/null cases in a real browser engine.
 */
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import '../../../../i18n';
import { YtMusicBadge } from '../YtMusicBadge';
import type { YtMusicMatch } from '../../lib/playlistTypes';

function renderBadge(match: YtMusicMatch | null | undefined) {
  return render(
    <MantineProvider defaultColorScheme="light">
      <YtMusicBadge
        match={match}
        playlistId="pl1"
        trackId="t1"
        track={{ title: 'Test Track', artists: [] }}
      />
    </MantineProvider>,
  );
}

describe('YtMusicBadge — browser smoke', () => {
  it('renders a link to YT Music when matched', () => {
    renderBadge({
      status: 'matched',
      video_id: 'vid1',
      url: 'https://music.youtube.com/watch?v=vid1',
    });
    expect(screen.getByRole('link')).toHaveAttribute(
      'href',
      'https://music.youtube.com/watch?v=vid1',
    );
  });

  it('renders no link for pending', () => {
    renderBadge({ status: 'pending' });
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('renders nothing when match is null', () => {
    renderBadge(null);
    // No link and no labeled icon should be present
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('renders a same-sized control for every status (no column shift)', () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const statuses: YtMusicMatch[] = [
      { status: 'matched', video_id: 'v', url: 'https://music.youtube.com/watch?v=v' },
      { status: 'pending' },
      { status: 'needs_review' },
      { status: 'not_found' },
    ];
    const { container } = render(
      <MantineProvider defaultColorScheme="light">
        <QueryClientProvider client={qc}>
          <div>
            {statuses.map((m, i) => (
              <YtMusicBadge
                key={i} match={m} playlistId="pl1" trackId={`t${i}`}
                track={{ title: 'X', artists: [] }}
              />
            ))}
          </div>
        </QueryClientProvider>
      </MantineProvider>,
    );
    const controls = Array.from(
      container.querySelectorAll('.mantine-ActionIcon-root'),
    ) as HTMLElement[];
    expect(controls).toHaveLength(4);
    const { offsetWidth: w, offsetHeight: h } = controls[0]!;
    expect(w).toBeGreaterThan(0);
    for (const el of controls) {
      expect(el.offsetWidth).toBe(w);
      expect(el.offsetHeight).toBe(h);
    }
  });
});
