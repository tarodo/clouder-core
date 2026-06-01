import { ActionIcon, Tooltip } from '@mantine/core';
import { IconPlayerPauseFilled, IconPlayerPlayFilled } from '@tabler/icons-react';

export interface PlayPauseButtonProps {
  /** This row is the playback's current track. */
  isCurrent: boolean;
  /** Playback is actively playing (only meaningful when isCurrent). */
  isPlaying: boolean;
  /** Track is playable (has a Spotify match). */
  canPlay: boolean;
  /** Start this track (used when the row is not the current track). */
  onPlay: () => void;
  /** Toggle play/pause of the current track (pause keeps position). */
  onToggle: () => void;
  playLabel: string;
  pauseLabel: string;
  unavailableLabel: string;
  size?: number;
}

/**
 * Row play/pause control. Shows Pause on the active, playing track so it is
 * distinguishable beyond the row highlight; clicking it pauses (and a second
 * click resumes). Non-current rows show Play and start their track.
 */
export function PlayPauseButton({
  isCurrent,
  isPlaying,
  canPlay,
  onPlay,
  onToggle,
  playLabel,
  pauseLabel,
  unavailableLabel,
  size = 16,
}: PlayPauseButtonProps) {
  const showPause = isCurrent && isPlaying;
  const label = !canPlay ? unavailableLabel : showPause ? pauseLabel : playLabel;
  const handleClick = isCurrent ? onToggle : onPlay;

  return (
    <Tooltip label={label}>
      <ActionIcon
        variant="subtle"
        size="md"
        disabled={!canPlay}
        onClick={canPlay ? handleClick : undefined}
        aria-label={label}
      >
        {showPause ? (
          <IconPlayerPauseFilled size={size} />
        ) : (
          <IconPlayerPlayFilled size={size} />
        )}
      </ActionIcon>
    </Tooltip>
  );
}
