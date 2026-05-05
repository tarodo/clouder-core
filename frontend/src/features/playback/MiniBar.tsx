import { Group, Stack, Text, ActionIcon } from '@mantine/core';
import { IconPlayerPlayFilled, IconPlayerPauseFilled, IconX } from '@tabler/icons-react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import classes from './MiniBar.module.css';
import type { PlaybackTrack, QueueStatus } from './lib/types';

export interface MiniBarProps {
  track: PlaybackTrack | null;
  state: QueueStatus;
  sourceHref: string;
  onPlayPause: () => void;
  onClose: () => void;
}

export function MiniBar({ track, state, sourceHref, onPlayPause, onClose }: MiniBarProps) {
  const { t } = useTranslation();
  if (!track) return null;
  const isPlaying = state === 'playing' || state === 'buffering';
  return (
    <div
      className={classes.root}
      role="region"
      aria-label={t('playback.minibar.now_playing_aria', { title: track.title })}
    >
      <Group gap="md" align="center" wrap="nowrap" className={classes.inner}>
        <div className={classes.cover}>
          {track.cover_url ? (
            <img src={track.cover_url} alt="" className={classes.coverImg} />
          ) : null}
        </div>
        <Stack gap={2} flex={1} miw={0}>
          <Link
            to={sourceHref}
            className={classes.titleLink}
            aria-label={t('playback.minibar.open_source')}
          >
            <Text fw={600} truncate>
              {track.title}
            </Text>
          </Link>
          <Text size="sm" c="dimmed" truncate>
            {track.artists}
          </Text>
        </Stack>
        <ActionIcon
          variant="subtle"
          radius="xl"
          onClick={onPlayPause}
          aria-label={
            isPlaying ? t('playback.controls.pause_aria') : t('playback.controls.play_aria')
          }
        >
          {isPlaying ? <IconPlayerPauseFilled /> : <IconPlayerPlayFilled />}
        </ActionIcon>
        <ActionIcon
          variant="subtle"
          radius="xl"
          onClick={onClose}
          aria-label={t('playback.controls.close_aria')}
        >
          <IconX />
        </ActionIcon>
      </Group>
    </div>
  );
}
