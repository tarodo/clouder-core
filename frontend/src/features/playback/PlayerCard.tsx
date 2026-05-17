import { Paper, Group, Stack, Text, Title, ActionIcon, Anchor, Slider, Button } from '@mantine/core';
import {
  IconPlayerPlayFilled,
  IconPlayerPauseFilled,
  IconAlertCircle,
  IconWifiOff,
  IconPlayerSkipBackFilled,
  IconPlayerSkipForwardFilled,
  IconExternalLink,
} from '@tabler/icons-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import classes from './PlayerCard.module.css';
import type { PlaybackTrack } from './lib/types';
import { useScrubDebounce } from './useScrubDebounce';
import { pctToMs } from './lib/seekHotkeys';

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
  /**
   * If false, hides the title/subline Stack entirely. Used by mobile
   * CurateSession to avoid duplicating CurateCard's metadata.
   */
  showText?: boolean;
  /**
   * Optional metadata row (BPM · key · label · length etc.) rendered below
   * the subline on desktop. CurateSession passes a custom node so PlayerCard
   * stays unaware of the BucketTrack shape.
   */
  metaRow?: ReactNode;
  /**
   * Optional mix name (e.g. "Original Mix", "Extended"), rendered between
   * Title and the artists subline. CurateSession passes BucketTrack.mix_name.
   */
  mixName?: string | null;
  /**
   * When true, renders a row of 5 chips (0/20/40/60/80%) directly below the
   * progress slider for fast mobile seeking. CurateSession sets this only on
   * mobile breakpoints; PlayerCard itself stays layout-agnostic.
   */
  mobileSeekChips?: boolean;
  /**
   * Optional slot rendered below the subline and above metaRow. T17 passes
   * <DeviceIndicator mode="full" ... /> here. When null/undefined, renders nothing.
   */
  deviceIndicator?: ReactNode;
  /**
   * Optional full-width slot rendered AFTER the main Group (cover + text +
   * controls) and BEFORE the scrubber. Useful when the meta you want to show
   * is wider than the text Stack next to the cover can fit (e.g. category
   * player's label + BPM band).
   */
  belowMainRow?: ReactNode;
  /** Spotify external open href; when set, renders an icon button at top-right. */
  spotifyHref?: string;
  /** Tooltip / aria text for the Spotify external icon. */
  spotifyAriaLabel?: string;
  onPlayPause: () => void;
  onPrev: () => void;
  onNext: () => void;
  onRetry: () => void;
  onOpenDevicePicker: () => void;
  onSeekMs: (ms: number) => void;
}

const SEEK_CHIP_PCTS = [0, 0.2, 0.4, 0.6, 0.8] as const;

const SCRUB_OPACITY: Record<PlayerCardState, number> = {
  idle: 1.0,
  playing: 1.0,
  // Treat transient buffering same as playing — no flicker on auto-advance.
  buffering: 1.0,
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
    showText = true,
    metaRow,
    mixName,
    deviceIndicator,
    belowMainRow,
    mobileSeekChips = false,
    spotifyHref,
    spotifyAriaLabel,
    onPlayPause,
    onPrev,
    onNext,
    onRetry,
    onOpenDevicePicker,
    onSeekMs,
  } = props;

  const isMini = variant === 'mini';
  // No Loader during transient `buffering`/`loading` — pause-button flashes
  // were distracting on auto-advance. Pause/Play icon is enough; the SDK
  // converges back to a stable state in milliseconds.
  const showAsAlert = state === 'error';
  const showAsWifiOff = state === 'disconnected' || state === 'empty-bucket';
  const showAsPause = state === 'playing' || state === 'buffering';

  const centerIcon = showAsAlert ? (
    <IconAlertCircle style={{ color: 'var(--color-danger)' }} />
  ) : showAsWifiOff ? (
    <IconWifiOff style={{ color: 'var(--color-fg-muted)' }} />
  ) : showAsPause ? (
    <IconPlayerPauseFilled />
  ) : (
    <IconPlayerPlayFilled />
  );

  const centerAriaLabel = showAsPause
    ? t('playback.controls.pause_aria')
    : t('playback.controls.play_aria');

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
    ) : (
      <Text size="sm" c="dimmed" truncate>
        {track?.artists ?? ''}
      </Text>
    );

  const scrubDisabled = state === 'error' || state === 'disconnected' || state === 'empty-bucket';
  const progressMax = track?.duration_ms || 1;
  const scrub = useScrubDebounce(onSeekMs, 100);

  return (
    <Paper
      className={classes.root}
      data-state={state}
      data-variant={variant}
      p={isMini ? 'sm' : 'lg'}
      pb={mobileSeekChips ? 'sm' : undefined}
      radius="md"
      withBorder={isMini}
      style={{ position: 'relative' }}
    >
      {!isMini && spotifyHref ? (
        <ActionIcon
          component="a"
          href={spotifyHref}
          target="_blank"
          rel="noopener noreferrer"
          variant="subtle"
          radius="xl"
          size="md"
          aria-label={spotifyAriaLabel ?? 'Open in Spotify'}
          style={{ position: 'absolute', top: 12, right: 12, zIndex: 1 }}
        >
          <IconExternalLink size={16} />
        </ActionIcon>
      ) : null}
      <Group align="center" gap="lg" wrap="nowrap">
        <div className={classes.cover} data-mini={isMini || undefined}>
          {track?.cover_url ? (
            <img src={track.cover_url} alt="" className={classes.coverImg} />
          ) : null}
        </div>

        {showText ? (
          <Stack gap={4} flex={1} miw={0}>
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
            {mixName ? (
              <Text size="sm" c="var(--color-fg-muted)" truncate>
                {mixName}
              </Text>
            ) : null}
            {subline}
            {deviceIndicator}
            {metaRow}
          </Stack>
        ) : (
          <div style={{ flex: 1 }} />
        )}

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

      {belowMainRow && !isMini ? (
        <div style={{ marginTop: 8 }}>{belowMainRow}</div>
      ) : null}

      <Slider
        className={classes.scrub}
        value={positionMs}
        min={0}
        max={progressMax}
        size="xs"
        thumbSize={isMini ? 0 : 12}
        label={null}
        disabled={scrubDisabled}
        onChange={scrub.onChange}
        onChangeEnd={scrub.onChangeEnd}
        style={{ opacity: SCRUB_OPACITY[state], marginTop: isMini ? 4 : mobileSeekChips ? 8 : 16 }}
        aria-label={t('playback.controls.scrub_aria')}
      />
      {mobileSeekChips ? (
        <Group gap={4} wrap="nowrap" mt={4} justify="space-between">
          {SEEK_CHIP_PCTS.map((pct) => {
            const label = `${Math.round(pct * 100)}%`;
            return (
              <Button
                key={pct}
                size="compact-xs"
                variant="light"
                color="gray"
                disabled={scrubDisabled}
                onClick={() => onSeekMs(pctToMs(pct, progressMax))}
                aria-label={t('playback.controls.seek_chip_aria_pct', { pct: Math.round(pct * 100) })}
                className={classes.seekChip}
              >
                {label}
              </Button>
            );
          })}
        </Group>
      ) : null}
    </Paper>
  );
}
