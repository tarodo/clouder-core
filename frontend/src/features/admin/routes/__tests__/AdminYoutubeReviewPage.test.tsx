import { describe, expect, it } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { testTheme } from '../../../../test/theme';
import { AdminYoutubeReviewPage } from '../AdminYoutubeReviewPage';

const review = () => ({
  style_name: 'Tech House',
  week_year: 2026,
  week_number: 40,
  tracks: [
    {
      track_id: 't1',
      title: 'Night Drive',
      mix_name: 'Extended Mix',
      artists: 'Zeta',
      length_ms: 390000,
      spotify_url: 'https://open.spotify.com/track/sp1',
      candidates: [
        {
          vendor_track_id: 'dQw4w9WgXcQ', title: 'Night Drive', artists: ['Zeta'],
          album: null, duration_ms: 201000,
          url: 'https://music.youtube.com/watch?v=dQw4w9WgXcQ', score: 0.9,
        },
        {
          vendor_track_id: 'aaaaaaaaaaa', title: 'Night Drive (Zeta Remix)', artists: ['Zeta'],
          album: null, duration_ms: 330000,
          url: 'https://music.youtube.com/watch?v=aaaaaaaaaaa', score: 0.7,
        },
      ],
    },
    {
      track_id: 't2', title: 'Day Ride', mix_name: null, artists: 'Alpha', length_ms: null,
      spotify_url: null, candidates: [],
    },
  ],
});

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <MemoryRouter initialEntries={['/admin/youtube-review?style=90&year=2026&week=40']}>
          <Routes>
            <Route path="/admin/youtube-review" element={<AdminYoutubeReviewPage />} />
          </Routes>
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('AdminYoutubeReviewPage', () => {
  it('lists each track with its Spotify link and YouTube candidates', async () => {
    let asked = '';
    server.use(
      http.get('http://localhost/admin/youtube/review', ({ request }) => {
        asked = new URL(request.url).search;
        return HttpResponse.json(review());
      }),
    );
    renderPage();
    const row = await screen.findByRole('article', { name: 'Night Drive' });
    expect(asked).toBe('?style_id=90&week_year=2026&week_number=40');
    expect(screen.getByText(/Tech House · Wk 40 · 2 tracks/)).toBeInTheDocument();
    expect(within(row).getByText('Night Drive (Extended Mix)')).toBeInTheDocument();
    expect(within(row).getByText('Zeta · 6:30')).toBeInTheDocument();
    expect(within(row).getByRole('link', { name: 'Open on Spotify' })).toHaveAttribute(
      'href', 'https://open.spotify.com/track/sp1',
    );
    const youtube = within(row).getAllByRole('link', { name: 'Open on YouTube' });
    expect(youtube[0]).toHaveAttribute('href', 'https://music.youtube.com/watch?v=dQw4w9WgXcQ');
    expect(within(row).getByText('Zeta · 3:21 · 0.90')).toBeInTheDocument();
    expect(within(screen.getByRole('article', { name: 'Day Ride' })).queryByRole(
      'link', { name: 'Open on Spotify' },
    )).toBeNull();
  });

  it('picks a candidate and drops the track from the list', async () => {
    const posted: Array<{ id: string; body: unknown }> = [];
    server.use(
      http.get('http://localhost/admin/youtube/review', () => HttpResponse.json(review())),
      http.post('http://localhost/admin/youtube/review/:id', async ({ params, request }) => {
        posted.push({ id: String(params.id), body: await request.json() });
        return HttpResponse.json({ track_id: params.id, action: 'accept' });
      }),
    );
    renderPage();
    const row = await screen.findByRole('article', { name: 'Night Drive' });
    const picks = within(row).getAllByRole('button', { name: 'Pick this one' });
    await userEvent.click(picks[1] as HTMLElement);
    await waitFor(() => expect(screen.queryByRole('article', { name: 'Night Drive' })).toBeNull());
    expect(posted).toEqual([
      { id: 't1', body: { action: 'accept', vendor_track_id: 'aaaaaaaaaaa' } },
    ]);
  });

  it('marks a track as not on YouTube', async () => {
    const posted: unknown[] = [];
    server.use(
      http.get('http://localhost/admin/youtube/review', () => HttpResponse.json(review())),
      http.post('http://localhost/admin/youtube/review/:id', async ({ request }) => {
        posted.push(await request.json());
        return HttpResponse.json({ track_id: 't2', action: 'reject' });
      }),
    );
    renderPage();
    const row = await screen.findByRole('article', { name: 'Day Ride' });
    await userEvent.click(within(row).getByRole('button', { name: 'Not on YouTube' }));
    await waitFor(() => expect(screen.queryByRole('article', { name: 'Day Ride' })).toBeNull());
    expect(posted).toEqual([{ action: 'reject' }]);
  });

  it('says so when nothing is left to review', async () => {
    server.use(
      http.get('http://localhost/admin/youtube/review', () =>
        HttpResponse.json({ ...review(), style_name: null, tracks: [] }),
      ),
    );
    renderPage();
    expect(await screen.findByText('Nothing left to review in this week.')).toBeInTheDocument();
  });
});
