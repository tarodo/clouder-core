import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { telemetry } from '../../../lib/telemetry/sdk';
import { AddTracksModal } from './AddTracksModal';

vi.mock('../../../hooks/useStyles', () => ({
  useStyles: () => ({ data: { items: [{ id: 's1', name: 'Style' }] } }),
}));
vi.mock('../../categories/hooks/useCategoriesByStyle', () => ({
  useCategoriesByStyle: () => ({ data: { items: [{ id: 'c1', name: 'Cat' }] } }),
}));
vi.mock('../../categories/hooks/useCategoryTracks', () => ({
  useCategoryTracks: () => ({ data: { pages: [{ items: [{ id: 't1', title: 'Song A' }] }] } }),
}));
const mutateAsync = vi.fn().mockResolvedValue({ added: ['t1'], skipped_duplicates: [], position_after: 1 });
vi.mock('../hooks/useAddTracksToPlaylist', () => ({
  useAddTracksToPlaylist: () => ({ mutateAsync, isPending: false }),
}));

function renderModal() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <AddTracksModal opened playlistId="pl-1" onClose={() => {}} onAdded={() => {}} />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('AddTracksModal telemetry', () => {
  beforeEach(() => vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true'));
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    mutateAsync.mockClear();
  });

  it('emits playlist_add with track_ids from the selected set and the source category', async () => {
    const spy = vi.spyOn(telemetry, 'track');
    renderModal();
    // pick style + category so the track list renders
    await userEvent.click(screen.getByLabelText(/style/i, { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Style' }));
    await userEvent.click(screen.getByLabelText(/category/i, { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Cat' }));
    await userEvent.click(await screen.findByText('Song A'));
    await userEvent.click(screen.getByRole('button', { name: /add|submit/i }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        'playlist_add',
        expect.objectContaining({
          track_ids: ['t1'],
          playlist_id: 'pl-1',
          track_count: 1,
          source_category_id: 'c1',
        }),
      ),
    );
  });
});
