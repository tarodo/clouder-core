import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../test/theme';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../../i18n';
import type { ReactElement } from 'react';
import { PlayerCard } from '../PlayerCard';
import type { PlaybackTrack } from '../lib/types';

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

  it('renders buffering state with Pause icon (no badge — F6 fix)', () => {
    // F6 (commit 2b6a1b4) removed the visible "Buffering…" badge + Loader.
    // The center button shows the Pause icon during buffering instead so the
    // pause-button doesn't flash on auto-advance. Verify the data-state
    // attribute survives + the center button reads as "Pause".
    const { container } = render(wrap(<PlayerCard {...baseProps} state="buffering" />));
    expect(container.querySelector('[data-state="buffering"]')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /pause/i })).toBeInTheDocument();
  });

  it('renders paused with data-state attribute', () => {
    const { container } = render(wrap(<PlayerCard {...baseProps} state="paused" />));
    expect(container.querySelector('[data-state="paused"]')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^play$/i })).toBeInTheDocument();
  });

  it('renders 5 seek chips when mobileSeekChips is true and clicking 40% chip calls onSeekMs(0.4 * duration)', () => {
    const onSeekMs = vi.fn();
    const track: PlaybackTrack = {
      id: 't1',
      title: 'T',
      artists: 'A',
      duration_ms: 200_000,
      spotify_id: 'sp1',
      cover_url: null,
    };
    render(
      wrap(
        <PlayerCard
          variant="full"
          state="playing"
          track={track}
          positionMs={0}
          mobileSeekChips
          onPlayPause={() => {}}
          onPrev={() => {}}
          onNext={() => {}}
          onRetry={() => {}}
          onOpenDevicePicker={() => {}}
          onSeekMs={onSeekMs}
        />,
      ),
    );
    const chip0 = screen.getByRole('button', { name: /Seek to 0%/i });
    const chip20 = screen.getByRole('button', { name: /Seek to 20%/i });
    const chip40 = screen.getByRole('button', { name: /Seek to 40%/i });
    const chip60 = screen.getByRole('button', { name: /Seek to 60%/i });
    const chip80 = screen.getByRole('button', { name: /Seek to 80%/i });
    expect(chip0).toBeInTheDocument();
    expect(chip20).toBeInTheDocument();
    expect(chip60).toBeInTheDocument();
    expect(chip80).toBeInTheDocument();
    fireEvent.click(chip40);
    expect(onSeekMs).toHaveBeenCalledWith(80_000);
  });

  it('omits seek chips when mobileSeekChips is false / undefined', () => {
    render(
      wrap(
        <PlayerCard
          variant="full"
          state="playing"
          track={null}
          positionMs={0}
          onPlayPause={() => {}}
          onPrev={() => {}}
          onNext={() => {}}
          onRetry={() => {}}
          onOpenDevicePicker={() => {}}
          onSeekMs={() => {}}
        />,
      ),
    );
    expect(screen.queryByRole('button', { name: /Seek to 40%/i })).toBeNull();
  });

  it('seek chips are disabled when state is disconnected', () => {
    const onSeekMs = vi.fn();
    render(
      wrap(
        <PlayerCard
          variant="full"
          state="disconnected"
          track={null}
          positionMs={0}
          mobileSeekChips
          onPlayPause={() => {}}
          onPrev={() => {}}
          onNext={() => {}}
          onRetry={() => {}}
          onOpenDevicePicker={() => {}}
          onSeekMs={onSeekMs}
        />,
      ),
    );
    const chip40 = screen.getByRole('button', { name: /Seek to 40%/i });
    expect(chip40).toBeDisabled();
    fireEvent.click(chip40);
    expect(onSeekMs).not.toHaveBeenCalled();
  });
});
