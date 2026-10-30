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

  it('hideText leaves the stats: the player names the track, artists and label', () => {
    render(wrap(<CurateCard track={mkTrack({ key_camelot: '8A' })} hideText />));
    expect(screen.queryByText('Sunset Drive')).toBeNull();
    expect(screen.queryByText('Big Room Records')).toBeNull();
    expect(screen.getByText('124')).toBeInTheDocument();
    expect(screen.getByText('8A')).toBeInTheDocument();
  });

  it('shows the key', () => {
    render(wrap(<CurateCard track={mkTrack({ key_camelot: '8A' })} />));
    expect(screen.getByText('8A')).toBeInTheDocument();
  });

  it('formats unknown BPM and length gracefully', () => {
    render(wrap(<CurateCard track={mkTrack({ bpm: null, length_ms: null })} />));
    expect(screen.getAllByText('—')).toHaveLength(2); // BPM and the missing key
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

describe('CurateCard AI badge', () => {
  it.each(['high', 'medium', 'low'] as const)('ai_verdict=%s shows an AI badge of that level', (level) => {
    render(wrap(<CurateCard track={mkTrack({ ai_verdict: level })} />));
    expect(screen.getByText('AI').closest('[data-level]')).toHaveAttribute('data-level', level);
  });

  it('shows nothing without a verdict', () => {
    render(wrap(<CurateCard track={mkTrack()} />));
    expect(screen.queryByText('AI')).not.toBeInTheDocument();
  });
});

describe('CurateCard AI reputation', () => {
  it('marks the artist and the label', () => {
    render(wrap(<CurateCard track={mkTrack({
      artists: [{ id: 'a-1', name: 'Artist A', role: 'artist', ai: { level: 1 as const, ai: 2, checked: 41, total: 300 } }],
      label_ai: { level: 3 as const, ai: 80, checked: 87, total: 869 },
    })} />));
    expect(screen.getByLabelText('AI level 1')).toBeInTheDocument();
    expect(screen.getByLabelText('AI level 3')).toBeInTheDocument();
  });
});
