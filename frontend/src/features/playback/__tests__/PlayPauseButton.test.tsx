import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { testTheme } from '../../../test/theme';
import { PlayPauseButton } from '../PlayPauseButton';

function setup(over: Partial<React.ComponentProps<typeof PlayPauseButton>> = {}) {
  const onPlay = vi.fn();
  const onToggle = vi.fn();
  render(
    <MantineProvider theme={testTheme}>
      <PlayPauseButton
        isCurrent={false}
        isPlaying={false}
        canPlay
        onPlay={onPlay}
        onToggle={onToggle}
        playLabel="Play track"
        pauseLabel="Pause track"
        unavailableLabel="No Spotify match"
        {...over}
      />
    </MantineProvider>,
  );
  return { onPlay, onToggle };
}

describe('PlayPauseButton', () => {
  it('shows Play and calls onPlay when not the current track', async () => {
    const { onPlay, onToggle } = setup();
    const btn = screen.getByRole('button', { name: 'Play track' });
    await userEvent.click(btn);
    expect(onPlay).toHaveBeenCalledTimes(1);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it('shows Pause and calls onToggle when current and playing', async () => {
    const { onPlay, onToggle } = setup({ isCurrent: true, isPlaying: true });
    const btn = screen.getByRole('button', { name: 'Pause track' });
    await userEvent.click(btn);
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onPlay).not.toHaveBeenCalled();
  });

  it('shows Play and calls onToggle when current and paused', async () => {
    const { onPlay, onToggle } = setup({ isCurrent: true, isPlaying: false });
    const btn = screen.getByRole('button', { name: 'Play track' });
    await userEvent.click(btn);
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onPlay).not.toHaveBeenCalled();
  });

  it('is disabled when not playable', () => {
    setup({ canPlay: false });
    expect(screen.getByRole('button', { name: 'No Spotify match' })).toBeDisabled();
  });
});
