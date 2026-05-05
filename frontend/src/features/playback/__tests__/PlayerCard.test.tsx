import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../test/theme';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../../i18n';
import type { ReactElement } from 'react';
import { PlayerCard } from '../PlayerCard';

const sampleTrack = {
  id: 't1',
  title: 'Title',
  artists: 'Artist 1, Artist 2',
  cover_url: null,
  duration_ms: 180_000,
  spotify_id: 'sp1',
};

function wrap(ui: ReactElement) {
  return (
    <MantineProvider theme={testTheme}>
      <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>
    </MantineProvider>
  );
}

const baseProps = {
  variant: 'full' as const,
  track: sampleTrack,
  positionMs: 0,
  onPlayPause: vi.fn(),
  onPrev: vi.fn(),
  onNext: vi.fn(),
  onRetry: vi.fn(),
  onOpenDevicePicker: vi.fn(),
  onSeekMs: vi.fn(),
};

describe('PlayerCard', () => {
  it('renders idle state with Play button', () => {
    render(wrap(<PlayerCard {...baseProps} state="idle" />));
    expect(screen.getByRole('button', { name: /^play$/i })).toBeInTheDocument();
  });

  it('renders playing state with Pause button', () => {
    render(wrap(<PlayerCard {...baseProps} state="playing" />));
    expect(screen.getByRole('button', { name: /pause/i })).toBeInTheDocument();
  });

  it('renders error state with Retry link', async () => {
    const onRetry = vi.fn();
    render(wrap(<PlayerCard {...baseProps} state="error" onRetry={onRetry} />));
    await userEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(onRetry).toHaveBeenCalled();
  });

  it('renders disconnected state with device picker link', async () => {
    const onOpenDevicePicker = vi.fn();
    render(wrap(<PlayerCard {...baseProps} state="disconnected" onOpenDevicePicker={onOpenDevicePicker} />));
    await userEvent.click(screen.getByRole('button', { name: /open device picker/i }));
    expect(onOpenDevicePicker).toHaveBeenCalled();
  });

  it('renders empty-bucket state with copy', () => {
    render(wrap(<PlayerCard {...baseProps} state="empty-bucket" track={null} />));
    expect(screen.getByText(/нет треков с Spotify match/i)).toBeInTheDocument();
  });

  it('renders buffering state with Buffering badge', () => {
    render(wrap(<PlayerCard {...baseProps} state="buffering" />));
    expect(screen.getByText(/buffering/i)).toBeInTheDocument();
  });

  it('renders paused with data-state attribute', () => {
    const { container } = render(wrap(<PlayerCard {...baseProps} state="paused" />));
    expect(container.querySelector('[data-state="paused"]')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^play$/i })).toBeInTheDocument();
  });
});
