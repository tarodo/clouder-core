import { Paper, Group, Stack, Text, Title, ActionIcon, Loader, Anchor, Badge, Slider } from '@mantine/core';
import {
  IconPlayerPlayFilled,
  IconPlayerPauseFilled,
  IconAlertCircle,
  IconWifiOff,
  IconPlayerSkipBackFilled,
  IconPlayerSkipForwardFilled,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import classes from './PlayerCard.module.css';
import type { PlaybackTrack } from './lib/types';

export type PlayerCardState =
  | 'idle'
  | 'playing'
  | 'paused'
  | 'buffering'
  | 'error'
  | 'disconnected'
  | 'empty-bucket';

export interface PlayerCardProps {
  variant: 'full' | 'mini';
  state: PlayerCardState;
  track: PlaybackTrack | null;
  positionMs: number;
  onPlayPause: () => void;
  onPrev: () => void;
  onNext: () => void;
  onRetry: () => void;
  onOpenDevicePicker: () => void;
  onSeekMs: (ms: number) => void;
}

const SCRUB_OPACITY: Record<PlayerCardState, number> = {
  idle: 1.0,
  playing: 1.0,
  buffering: 0.4,
  paused: 0.6,
  error: 0.4,
  disconnected: 0.3,
  'empty-bucket': 0.0,
};

export function PlayerCard(props: PlayerCardProps) {
  const { t } = useTranslation();
  const {
    variant,
    state,
    track,
    positionMs,
    onPlayPause,
    onPrev,
    onNext,
    onRetry,
    onOpenDevicePicker,
    onSeekMs,
  } = props;

  const isMini = variant === 'mini';
  const showAsLoader = state === 'buffering';
  const showAsAlert = state === 'error';
  const showAsWifiOff = state === 'disconnected' || state === 'empty-bucket';
  const showAsPause = state === 'playing';

  const centerIcon = showAsLoader ? (
    <Loader size={20} />
  ) : showAsAlert ? (
    <IconAlertCircle style={{ color: 'var(--color-danger)' }} />
  ) : showAsWifiOff ? (
    <IconWifiOff style={{ color: 'var(--color-fg-muted)' }} />
  ) : showAsPause ? (
    <IconPlayerPauseFilled />
  ) : (
    <IconPlayerPlayFilled />
  );

  const centerAriaLabel =
    state === 'playing' ? t('playback.controls.pause_aria') : t('playback.controls.play_aria');

  const subline =
    state === 'error' ? (
      <Text size="sm" c="var(--color-danger)">
        {t('playback.playback_failed')}
        {' · '}
        <Anchor component="button" type="button" onClick={onRetry}>
          {t('playback.retry')}
        </Anchor>
      </Text>
    ) : state === 'disconnected' ? (
      <Text size="sm" c="dimmed">
        {t('playback.reconnect_spotify')}
        {' · '}
        <Anchor component="button" type="button" onClick={onOpenDevicePicker}>
          {t('playback.open_device_picker')}
        </Anchor>
      </Text>
    ) : state === 'empty-bucket' ? (
      <Text size="sm" c="dimmed">
        {t('playback.empty_bucket_body')}
      </Text>
    ) : state === 'buffering' ? (
      <Group gap={6} wrap="nowrap">
        <Text size="sm" c="dimmed" truncate>
          {track?.artists ?? ''}
        </Text>
        <Badge size="xs" variant="light" ff="monospace">
          {t('playback.buffering')}
        </Badge>
      </Group>
    ) : (
      <Text size="sm" c="dimmed" truncate>
        {track?.artists ?? ''}
      </Text>
    );

  const scrubDisabled = state === 'error' || state === 'disconnected' || state === 'empty-bucket';
  const progressMax = track?.duration_ms || 1;

  return (
    <Paper
      className={classes.root}
      data-state={state}
      data-variant={variant}
      p={isMini ? 'sm' : 'lg'}
      radius="md"
      withBorder={isMini}
    >
      <Group align="center" gap="lg" wrap="nowrap">
        <div className={classes.cover} data-mini={isMini || undefined}>
          {track?.cover_url ? (
            <img src={track.cover_url} alt="" className={classes.coverImg} />
          ) : null}
        </div>

        <Stack gap={4} flex={1} miw={0}>
          <Text size="xs" tt="uppercase" c="dimmed" ff="monospace">
            {t('playback.now_playing')}
          </Text>
          <Title
            order={isMini ? 5 : 3}
            style={{
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {track?.title ?? '—'}
          </Title>
          {subline}
        </Stack>

        {!isMini ? (
          <ActionIcon
            size="lg"
            radius="xl"
            variant="subtle"
            onClick={onPrev}
            aria-label={t('playback.controls.prev_aria')}
          >
            <IconPlayerSkipBackFilled />
          </ActionIcon>
        ) : null}

        <ActionIcon
          size={isMini ? 'lg' : 44}
          radius="xl"
          variant="filled"
          color="dark.9"
          onClick={onPlayPause}
          disabled={state === 'error' || state === 'disconnected' || state === 'empty-bucket'}
          aria-label={centerAriaLabel}
        >
          {centerIcon}
        </ActionIcon>

        {!isMini ? (
          <ActionIcon
            size="lg"
            radius="xl"
            variant="subtle"
            onClick={onNext}
            aria-label={t('playback.controls.next_aria')}
          >
            <IconPlayerSkipForwardFilled />
          </ActionIcon>
        ) : null}
      </Group>

      <Slider
        className={classes.scrub}
        value={positionMs}
        min={0}
        max={progressMax}
        size="xs"
        thumbSize={isMini ? 0 : 12}
        label={null}
        disabled={scrubDisabled}
        onChange={onSeekMs}
        style={{ opacity: SCRUB_OPACITY[state], marginTop: isMini ? 4 : 16 }}
        aria-label={t('playback.controls.scrub_aria')}
      />
    </Paper>
  );
}
