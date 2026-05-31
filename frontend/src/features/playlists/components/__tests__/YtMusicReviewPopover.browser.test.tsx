import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import '../../../../i18n';
import { YtMusicReviewPopover } from '../YtMusicReviewPopover';

vi.mock('../../../../api/client', () => ({
  api: vi.fn(async (path: string) =>
    path.includes('match-candidates')
      ? { vendor: 'ytmusic', candidates: [
          { vendor_track_id: 'dQw4w9WgXcQ', title: 'Hold Me', artists: ['ARTYS'],
            album: 'EP', duration_ms: 418000,
            url: 'https://music.youtube.com/watch?v=dQw4w9WgXcQ', score: 0.9 }] }
      : { ytmusic: { status: 'matched', video_id: 'dQw4w9WgXcQ',
          url: 'https://music.youtube.com/watch?v=dQw4w9WgXcQ', confidence: 1 } }),
}));

function setup(status: 'needs_review' | 'not_found') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <YtMusicReviewPopover playlistId="pl1" trackId="t1" status={status}
          track={{ title: 'Hold Me In Heaven', artists: [{ id: 'a', name: 'ARTYS' }] }} />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe('YtMusicReviewPopover', () => {
  it('needs_review: opens, lists a candidate, and accepts it', async () => {
    setup('needs_review');
    await userEvent.click(screen.getByRole('button', { name: /review/i }));
    await waitFor(() => expect(screen.getByText('Hold Me')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /accept/i }));
  });

  it('not_found: opens a manual-link form with no candidate fetch', async () => {
    setup('not_found');
    await userEvent.click(screen.getByRole('button', { name: /review/i }));
    // no candidate list for a not_found track
    await waitFor(() => expect(screen.getByPlaceholderText(/music\.youtube\.com/i)).toBeInTheDocument());
    expect(screen.queryByText('Hold Me')).toBeNull();
    // a valid pasted link enables "Use link" and submits
    await userEvent.type(
      screen.getByPlaceholderText(/music\.youtube\.com/i),
      'https://music.youtube.com/watch?v=dQw4w9WgXcQ',
    );
    await userEvent.click(screen.getByRole('button', { name: /use link/i }));
  });
});
