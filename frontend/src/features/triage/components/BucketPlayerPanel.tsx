import { useEffect, useMemo, useRef } from 'react';
import { Group, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { usePlayback } from '../../playback/usePlayback';
import { usePlaybackHotkeys } from '../../playback/usePlaybackHotkeys';
import { PlayerCard, type PlayerCardState } from '../../playback/PlayerCard';
import { DeviceIndicator } from '../../playback/DeviceIndicator';
import type { BucketTrack } from '../hooks/useBucketTracks';
import { useTriageBlock } from '../hooks/useTriageBlock';
import { useBucketDistribute } from '../hooks/useBucketDistribute';
import { BucketDistributeButtons } from './BucketDistributeButtons';
import { moveDestinationsFor } from '../lib/bucketLabels';
import { LabelTile } from '../../library/components/LabelTile';

export interface BucketPlayerPanelProps {
  blockId: string;
  bucketId: string;
  /** Visible bucket tracks, used to look up label/BPM for the playing track. */
  items: BucketTrack[];
}

export function BucketPlayerPanel({ blockId, bucketId, items }: BucketPlayerPanelProps) {
  const { t } = useTranslation();
  const playback = usePlayback();
  const current = playback.track.current;

  const { data: block } = useTriageBlock(blockId);
  const blockBuckets = block?.buckets ?? [];
  const distribute = useBucketDistribute({
    blockId,
    bucketId,
    styleId: block?.style_id ?? '',
    buckets: blockBuckets,
  });
  const destinations =
    block?.status === 'IN_PROGRESS'
      ? moveDestinationsFor(blockBuckets, bucketId).filter(
          (b) => b.bucket_type === 'STAGING' || b.bucket_type === 'DISCARD',
        )
      : [];

  const richTrack = useMemo<BucketTrack | null>(() => {
    const id = current?.id;
    if (!id) return null;
    return items.find((it) => it.track_id === id) ?? null;
  }, [items, current?.id]);
  const lastRichRef = useRef<BucketTrack | null>(null);
  useEffect(() => {
    if (richTrack) lastRichRef.current = richTrack;
  }, [richTrack]);
  useEffect(() => {
    if (!current) lastRichRef.current = null;
  }, [current]);
  const effectiveRich =
    richTrack ??
    (lastRichRef.current?.track_id === current?.id ? lastRichRef.current : null);

  const playerState: PlayerCardState = (() => {
    if (playback.sdk.error?.kind === 'init') return 'disconnected';
    const status = playback.queue.status;
    if (status === 'error') return 'error';
    if (status === 'idle' || status === 'ended') return 'idle';
    if (status === 'loading' || status === 'buffering') return 'buffering';
    if (status === 'disconnected') return 'disconnected';
    return status; // 'playing' | 'paused'
  })();

  usePlaybackHotkeys({
    onTogglePlayPause: () => void playback.controls.togglePlayPause(),
    onPrev: () => void playback.controls.prev(),
    onNext: () => void playback.controls.next(),
    onSeekRelative: (deltaMs) =>
      void playback.controls.seekMs(playback.track.positionMs + deltaMs),
    onSeekPct: (p) => void playback.controls.seekPct(p),
  });

  if (!current) {
    return (
      <Stack gap="md" style={{ width: 520, flexShrink: 0, minWidth: 0 }}>
        <Text c="dimmed">{t('triage.bucket_player.empty.pick_track')}</Text>
      </Stack>
    );
  }

  const spotifyHref = current.spotify_id
    ? `https://open.spotify.com/track/${current.spotify_id}`
    : undefined;

  const metaRow =
    effectiveRich != null ? (
      <Group gap="md" wrap="wrap" mt={4} style={{ minWidth: 0 }}>
        {effectiveRich.label_name ? (
          <Text size="sm" c="var(--color-fg-muted)" truncate style={{ flex: 1 }}>
            {effectiveRich.label_name}
          </Text>
        ) : null}
        {effectiveRich.bpm != null ? (
          <Text size="sm" c="var(--color-fg-muted)" className="font-mono">
            {effectiveRich.bpm} BPM
          </Text>
        ) : null}
      </Group>
    ) : null;

  return (
    <Stack gap="md" style={{ width: 520, flexShrink: 0, minWidth: 0 }}>
      <PlayerCard
        variant="full"
        state={playerState}
        track={current}
        positionMs={playback.track.positionMs}
        mixName={effectiveRich?.mix_name ?? null}
        belowMainRow={metaRow}
        showTimes
        spotifyHref={spotifyHref}
        spotifyAriaLabel={t('triage.bucket_player.open_in_spotify_aria', {
          title: current.title,
        })}
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
      />
      <BucketDistributeButtons destinations={destinations} onDistribute={distribute} />
      <LabelTile
        labelId={effectiveRich?.label_id ?? null}
        labelName={effectiveRich?.label_name ?? null}
        styleId={block?.style_id ?? ''}
      />
    </Stack>
  );
}
