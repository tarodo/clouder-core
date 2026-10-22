import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { CoverageMatrix } from '../CoverageMatrix';
import type { CoveragePayload } from '../../hooks/useCoverage';

const sample: CoveragePayload = {
  week_year: 2026,
  weeks_in_year: 52,
  styles: [
    {
      style_id: 90,
      clouder_style_id: 'uuid-th',
      style_name: 'Tech House',
      is_hidden: false,
      cells: [
        {
          week_number: 1,
          status: 'completed',
          run_id: 'r',
          item_count: 10,
          is_custom_range: false,
          period_start: '2026-01-03',
          period_end: '2026-01-09',
          started_at: '2026-01-04T09:00:00Z',
          finished_at: '2026-01-04T09:01:00Z',
        },
      ],
      spotify_weeks: [
        {
          week_number: 1, total: 50, found: 45, not_found: 3,
          pending: 1, no_isrc: 1,
        },
        {
          week_number: 5, total: 8, found: 8, not_found: 0,
          pending: 0, no_isrc: 0,
        },
      ],
      youtube_weeks: [
        {
          week_number: 1, total: 50, found: 40, review: 4, not_found: 2, pending: 4,
        },
        {
          week_number: 7, total: 6, found: 0, review: 0, not_found: 0, pending: 6,
        },
      ],
    },
  ],
};

function ui(props: React.ComponentProps<typeof CoverageMatrix>) {
  return (
    <MantineProvider theme={testTheme}>
      <CoverageMatrix {...props} />
    </MantineProvider>
  );
}

describe('CoverageMatrix', () => {
  it('renders one row per style and week-1 cell loaded', () => {
    render(ui({ data: sample, onCellClick: vi.fn() }));
    expect(screen.getByText('Tech House')).toBeInTheDocument();
    expect(
      screen.getByLabelText('Tech House week 1 loaded'),
    ).toBeInTheDocument();
  });

  it('fires onCellClick with style_id+week', async () => {
    const onClick = vi.fn();
    render(ui({ data: sample, onCellClick: onClick }));
    await userEvent.click(screen.getByLabelText('Tech House week 1 loaded'));
    expect(onClick).toHaveBeenCalledWith(90, 1);
  });

  it('renders empty cells for missing weeks', () => {
    render(ui({ data: sample, onCellClick: vi.fn() }));
    expect(
      screen.getByLabelText('Tech House week 5 empty'),
    ).toBeInTheDocument();
  });

  it('shows spotify stats in the tooltip on hover', async () => {
    render(ui({ data: sample, onCellClick: vi.fn() }));
    await userEvent.hover(screen.getByLabelText('Tech House week 1 loaded'));
    expect(
      await screen.findByText(/Spotify: 45\/50 found · 3 not found · 1 pending · 1 no ISRC/),
    ).toBeInTheDocument();
  });

  it('shows spotify stats on empty cells that have tracks', async () => {
    render(ui({ data: sample, onCellClick: vi.fn() }));
    await userEvent.hover(screen.getByLabelText('Tech House week 5 empty'));
    expect(
      await screen.findByText(/Spotify: 8\/8 found · 0 not found/),
    ).toBeInTheDocument();
  });

  it('shows youtube stats next to spotify in the tooltip', async () => {
    render(ui({ data: sample, onCellClick: vi.fn() }));
    await userEvent.hover(screen.getByLabelText('Tech House week 1 loaded'));
    expect(
      await screen.findByText(/YouTube: 40\/50 found · 4 review · 2 not found · 4 pending/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Spotify: 45\/50 found/)).toBeInTheDocument();
  });

  it('shows youtube stats on a week only youtube has numbers for', async () => {
    render(ui({ data: sample, onCellClick: vi.fn() }));
    await userEvent.hover(screen.getByLabelText('Tech House week 7 empty'));
    expect(
      await screen.findByText(/YouTube: 0\/6 found · 0 not found · 6 pending/),
    ).toBeInTheDocument();
  });
});
