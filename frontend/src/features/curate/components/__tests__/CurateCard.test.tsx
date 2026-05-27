// frontend/src/features/curate/components/__tests__/CurateCard.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { CurateCard } from '../CurateCard';
import type { BucketTrack } from '../../../triage/hooks/useBucketTracks';

const mkTrack = (overrides: Partial<BucketTrack> = {}): BucketTrack => ({
  track_id: 't1',
  title: 'Sunset Drive',
  mix_name: 'Original Mix',
  isrc: null,
  bpm: 124,
  length_ms: 360000,
  publish_date: '2026-04-15',
  spotify_release_date: '2026-04-15',
  spotify_id: 'sp-t1',
  release_type: 'single',
  is_ai_suspected: false,
  artists: [{ id: 'a-1', name: 'Artist A', role: 'artist' }, { id: 'a-2', name: 'Artist B', role: 'artist' }],
  label_id: 'lbl-x',
  label_name: 'Big Room Records',
  added_at: '2026-04-21T00:00:00Z',
  ...overrides,
});

const wrap = (ui: React.ReactElement) => (
  <MantineProvider theme={testTheme}>{ui}</MantineProvider>
);

describe('CurateCard', () => {
  it('renders title, mix, artists, label, BPM, length, release date', () => {
    render(wrap(<CurateCard track={mkTrack()} />));
    expect(screen.getByText('Sunset Drive')).toBeInTheDocument();
    expect(screen.getByText(/Original Mix/)).toBeInTheDocument();
    expect(screen.getByText('Artist A, Artist B')).toBeInTheDocument();
    expect(screen.getByText('Big Room Records')).toBeInTheDocument();
    expect(screen.getByText('124')).toBeInTheDocument();
    expect(screen.getByText('06:00')).toBeInTheDocument();
    expect(screen.getByText('2026-04-15')).toBeInTheDocument();
  });

  it('renders the AI badge when is_ai_suspected', () => {
    render(wrap(<CurateCard track={mkTrack({ is_ai_suspected: true })} />));
    expect(screen.getByText(/AI suspect/i)).toBeInTheDocument();
  });

  it('hides the AI badge when not suspected', () => {
    render(wrap(<CurateCard track={mkTrack({ is_ai_suspected: false })} />));
    expect(screen.queryByText(/AI suspect/i)).toBeNull();
  });

  // F6 (commit 2b6a1b4): the inline "Open in Spotify" link moved out of
  // CurateCard into PlayerCard's top-right corner. CurateCard now only renders
  // a fallback hint when spotify_id is null.
  it('shows fallback copy when spotify_id is null', () => {
    render(wrap(<CurateCard track={mkTrack({ spotify_id: null })} />));
    expect(screen.queryByRole('link', { name: /Spotify/i })).toBeNull();
    expect(screen.getByText(/No Spotify match/i)).toBeInTheDocument();
  });

  it('does NOT render the inline Open-in-Spotify link when spotify_id is present', () => {
    // Affordance moved to PlayerCard top-right icon.
    render(wrap(<CurateCard track={mkTrack()} />));
    expect(screen.queryByRole('link', { name: /Spotify/i })).toBeNull();
    expect(screen.queryByText(/No Spotify match/i)).toBeNull();
  });

  it('formats unknown BPM and length gracefully', () => {
    render(wrap(<CurateCard track={mkTrack({ bpm: null, length_ms: null })} />));
    expect(screen.getByText(/—/)).toBeInTheDocument();
  });

  // F6: the in-card Play ActionIcon was removed; the PlayerCard's center
  // button is now the only Play affordance. Play-button assertions live in
  // PlayerCard.test.tsx instead.
  describe('Play affordance (post-F6: removed)', () => {
    it('does not render a Play button inside the card', () => {
      render(wrap(<CurateCard track={mkTrack()} />));
      expect(
        screen.queryByRole('button', { name: /^play$/i }),
      ).toBeNull();
    });

    it('does not render a disabled Play button when spotify_id is null', () => {
      render(wrap(<CurateCard track={mkTrack({ spotify_id: null })} />));
      expect(
        screen.queryByRole('button', { name: /^play$/i }),
      ).toBeNull();
    });
  });
});
