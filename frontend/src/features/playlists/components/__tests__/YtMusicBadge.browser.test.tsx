/**
 * Browser-mode smoke for YtMusicBadge: verifies link rendering for matched
 * status and absence of link for pending/null cases in a real browser engine.
 */
import { MantineProvider } from '@mantine/core';
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
});
