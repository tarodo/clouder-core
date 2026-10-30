import { Group, Stack, Text } from '@mantine/core';
import { useEffect, useRef, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ArtistsPanel } from '../library/components/ArtistsPanel';
import { EntityLink } from '../library/components/EntityLinks';
import { LabelTile } from '../library/components/LabelTile';
import { DeviceIndicator } from './DeviceIndicator';
import type { PlaybackTrack } from './lib/types';
import { PlayerCard, type PlayerCardProps, type PlayerCardState } from './PlayerCard';
import type { PlaybackContextValue } from './PlaybackProvider';
import { TrackKey } from './TrackKey';
import { usePlayback } from './usePlayback';

/** The playing track as every player shows it, mapped from the page's own row. */
export interface PlayerTrackInfo {
  mixName: string | null;
  artists: ReadonlyArray<{ id: string; name: string; role?: string }>;
  /** A label without an id is named, not linked. */
  label: { id: string | null; name: string } | null;
  bpm: number | null;
  /** Shown only when given: the key's Camelot code, its name in the tooltip. */
  key?: { camelot: string | null; name: string | null };
  releaseDate?: string | null;
}

/**
 * The row of the playing track in *items*; while the list reloads, the last one seen of that same
 * track. Never another track's row: it would show the previous track's label, links and tags.
 */
export function usePlayingRow<T>(items: readonly T[], idOf: (row: T) => string): T | null {
  const id = usePlayback().track.current?.id ?? null;
  const row = (id && items.find((it) => idOf(it) === id)) || null;
  const last = useRef<T | null>(null);
  useEffect(() => {
    if (row) last.current = row;
  }, [row]);
  return row ?? (last.current && idOf(last.current) === id ? last.current : null);
}

/** The transport half of the player hotkeys: play/pause, prev/next, seek. */
export function transportHotkeys(playback: PlaybackContextValue) {
  return {
    onTogglePlayPause: () => void playback.controls.togglePlayPause(),
    onPrev: () => void playback.controls.prev(),
    onNext: () => void playback.controls.next(),
    onSeekRelative: (deltaMs: number) =>
      void playback.controls.seekMs(playback.track.positionMs + deltaMs),
    onSeekPct: (p: number) => void playback.controls.seekPct(p),
  };
}

function cardState(playback: PlaybackContextValue, emptyBucket: boolean): PlayerCardState {
  if (emptyBucket) return 'empty-bucket';
  if (playback.sdk.error?.kind === 'init') return 'disconnected';
  const status = playback.queue.status;
  if (status === 'error') return 'error';
  if (status === 'idle' || status === 'ended') return 'idle';
  if (status === 'loading' || status === 'buffering') return 'buffering';
  return status; // 'playing' | 'paused' | 'disconnected'
}

type Wired =
  | 'variant'
  | 'state'
  | 'positionMs'
  | 'onPlayPause'
  | 'onPrev'
  | 'onNext'
  | 'onRetry'
  | 'onOpenDevicePicker'
  | 'onSeekMs';

/**
 * The full PlayerCard wired to playback: transport, seek, devices and the Spotify link of *track*.
 * Any card prop given overrides the wiring.
 */
export function ConnectedPlayerCard({
  emptyBucket = false,
  ...props
}: Omit<PlayerCardProps, Wired> & {
  /** Nothing in the queue is on Spotify. */
  emptyBucket?: boolean;
}) {
  const { t } = useTranslation();
  const playback = usePlayback();
  const { track } = props;
  return (
    <PlayerCard
      variant="full"
      state={cardState(playback, emptyBucket)}
      positionMs={playback.track.positionMs}
      spotifyHref={track?.spotify_id ? `https://open.spotify.com/track/${track.spotify_id}` : undefined}
      spotifyAriaLabel={track ? t('playback.open_in_spotify_aria', { title: track.title }) : undefined}
      deviceIndicator={
        <DeviceIndicator
          mode="full"
          active={playback.devices.active}
          cloderTabId={playback.devices.cloderTabId}
          onOpen={(anchor) => playback.devices.open(anchor)}
        />
      }
      onPlayPause={() => void playback.controls.togglePlayPause()}
      onPrev={() => void playback.controls.prev()}
      onNext={() => void playback.controls.next()}
      onRetry={() => void playback.controls.play()}
      onOpenDevicePicker={() => playback.devices.open(null)}
      onSeekMs={(ms) => void playback.controls.seekMs(ms)}
      {...props}
    />
  );
}

/** Label, BPM, key and release date in one line under the card's main row; *children* below it. */
export function TrackMeta({ info, children }: { info: PlayerTrackInfo; children?: ReactNode }) {
  const { t } = useTranslation();
  const { label, bpm, key, releaseDate } = info;
  return (
    <Stack gap={2} mt={4}>
      <Group gap="md" wrap="wrap" style={{ minWidth: 0 }}>
        {label ? (
          <Group gap={4} wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
            <Text size="sm" c="var(--color-fg-muted)">
              {t('curate.card.label_label')}:
            </Text>
            <Text size="sm" c="var(--color-fg-muted)" truncate style={{ flex: 1 }}>
              {label.id ? <EntityLink kind="label" id={label.id} name={label.name} /> : label.name}
            </Text>
          </Group>
        ) : null}
        {bpm != null ? (
          <Text size="sm" c="var(--color-fg-muted)" className="font-mono">
            {bpm} BPM
          </Text>
        ) : null}
        {key ? <TrackKey camelot={key.camelot} name={key.name} size="sm" /> : null}
        {releaseDate ? (
          <Text size="sm" c="var(--color-fg-muted)" className="font-mono">
            {releaseDate}
          </Text>
        ) : null}
      </Group>
      {children}
    </Stack>
  );
}

/** The cards of the playing track's label and artists. */
export function TrackCards({ info }: { info: PlayerTrackInfo | null }) {
  return (
    <>
      <LabelTile labelId={info?.label?.id ?? null} labelName={info?.label?.name ?? null} />
      <ArtistsPanel artists={info?.artists ?? []} />
    </>
  );
}

export interface TrackPlayerProps {
  className?: string;
  /** What the page knows of the playing track; null while its row is unknown. */
  info: PlayerTrackInfo | null;
  /** Shown while nothing plays. */
  empty: string;
  /** Under the label/BPM line. */
  meta?: ReactNode;
  /** The page's own modules under the card. */
  children?: (track: PlaybackTrack) => ReactNode;
}

/** A page's player column: the playing track's card and meta, then the page's own modules. */
export function TrackPlayer({ className, info, empty, meta, children }: TrackPlayerProps) {
  const current = usePlayback().track.current;
  if (!current) {
    return (
      <Stack className={className} gap="md" data-player>
        <Text c="dimmed">{empty}</Text>
      </Stack>
    );
  }
  return (
    <Stack className={className} gap="md" data-player>
      <ConnectedPlayerCard
        track={current}
        mixName={info?.mixName ?? null}
        artistLinks={info?.artists}
        belowMainRow={info ? <TrackMeta info={info}>{meta}</TrackMeta> : null}
        showTimes
      />
      {children?.(current)}
    </Stack>
  );
}
