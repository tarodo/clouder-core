import { useCallback, useRef } from 'react';
import { Anchor, Group, Text } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { notifications } from '@mantine/notifications';
import { ApiError } from '../../../api/error';
import { usePlayback } from '../../playback/usePlayback';
import {
  takeSnapshot,
  undoMoveDirect,
  useMoveTracks,
  type MoveInput,
  type MoveSnapshot,
} from './useMoveTracks';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';

export interface UseBucketDistributeArgs {
  blockId: string;
  bucketId: string;
  styleId: string;
  /** Block buckets — used to label the destination in the success toast. */
  buckets: TriageBucket[];
}

/**
 * Move the currently-playing track from `bucketId` into `toBucketId`
 * (optimistic, with an Undo toast) and immediately play the next queued track.
 * No-op when nothing is playing. Undo restores the track to the bucket but does
 * not rewind playback (lean — unlike the full Curate undo).
 */
export function useBucketDistribute({
  blockId,
  bucketId,
  styleId,
  buckets,
}: UseBucketDistributeArgs): (toBucketId: string) => void {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const playback = usePlayback();
  const move = useMoveTracks(blockId, styleId);
  const undoInflight = useRef(false);

  return useCallback(
    (toBucketId: string) => {
      const current = playback.track.current;
      if (!current) return;
      const tracks = playback.queue.tracks;
      const idx = tracks.findIndex((q) => q.id === current.id);
      const successor = idx >= 0 ? tracks[idx + 1] ?? null : null;
      const toBucket = buckets.find((b) => b.id === toBucketId);

      const input: MoveInput = {
        fromBucketId: bucketId,
        toBucketId,
        trackIds: [current.id],
      };
      const snapshot: MoveSnapshot = takeSnapshot(qc, blockId, bucketId);

      move.mutate(input, {
        onSuccess: () => {
          const toastId = `bucket-distribute-${Date.now()}-${current.id}`;
          notifications.show({
            id: toastId,
            color: 'green',
            autoClose: 5000,
            message: (
              <Group justify="space-between" gap="md">
                <Text size="sm">
                  {t('triage.move.toast.moved', {
                    count: 1,
                    to: toBucket ? bucketLabel(toBucket, t) : '',
                  })}
                </Text>
                <Anchor
                  component="button"
                  onClick={async () => {
                    if (undoInflight.current || move.isPending) return;
                    undoInflight.current = true;
                    notifications.hide(toastId);
                    try {
                      await undoMoveDirect(qc, blockId, styleId, input, snapshot);
                      notifications.show({
                        message: t('triage.move.toast.undone'),
                        color: 'green',
                      });
                    } catch {
                      notifications.show({
                        message: t('triage.move.toast.undo_failed'),
                        color: 'red',
                      });
                    } finally {
                      undoInflight.current = false;
                    }
                  }}
                >
                  {t('triage.move.toast.undo_action')}
                </Anchor>
              </Group>
            ),
          });
        },
        onError: (err) => {
          const code = err instanceof ApiError ? err.code : 'unknown';
          let messageKey = 'triage.move.toast.error';
          if (code === 'target_bucket_inactive' || code === 'invalid_state') {
            messageKey = 'triage.move.toast.invalid_target';
          } else if (
            code === 'triage_block_not_found' ||
            code === 'bucket_not_found' ||
            code === 'tracks_not_in_source'
          ) {
            messageKey = 'triage.move.toast.stale_state';
          }
          notifications.show({ message: t(messageKey), color: 'red' });
        },
      });

      if (successor) {
        void playback.controls.play(undefined, successor);
      }
    },
    [playback, buckets, bucketId, blockId, styleId, qc, move, t],
  );
}
