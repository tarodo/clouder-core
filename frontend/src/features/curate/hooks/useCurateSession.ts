import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { notifications } from '@mantine/notifications';
import { useTriageBlock, type TriageBlock } from '../../triage/hooks/useTriageBlock';
import { useBucketTracks, type BucketTrack } from '../../triage/hooks/useBucketTracks';
import {
  useMoveTracks,
  takeSnapshot,
  undoMoveDirect,
  type MoveInput,
  type MoveSnapshot,
} from '../../triage/hooks/useMoveTracks';
import type { TriageBucket } from '../../triage/lib/bucketLabels';
import { ApiError } from '../../../api/error';
import {
  writeLastCurateLocation,
  writeLastCurateStyle,
} from '../lib/lastCurateLocation';

export interface UseCurateSessionArgs {
  blockId: string;
  bucketId: string;
  styleId: string;
}

export type CurateStatus = 'loading' | 'active' | 'empty' | 'error';

export interface CurateSession {
  status: CurateStatus;
  queue: BucketTrack[];
  currentTrack: BucketTrack | null;
  currentIndex: number;
  totalAssigned: number;
  destinations: TriageBucket[];
  block: TriageBlock | null;
  lastTappedBucketId: string | null;
  canUndo: boolean;
  assign: (toBucketId: string) => void;
  undo: () => void;
  skip: () => void;
  prev: () => void;
  openSpotify: () => void;
}

interface LastOp {
  input: MoveInput;
  snapshot: MoveSnapshot;
  trackIndex: number;
}

interface State {
  currentIndex: number;
  totalAssigned: number;
  lastTappedBucketId: string | null;
  lastOp: LastOp | null;
}

type Action =
  | { type: 'ASSIGN_BEGIN'; toBucketId: string; lastOp: LastOp }
  | { type: 'ASSIGN_REPLACE_BEGIN'; toBucketId: string; lastOp: LastOp }
  | { type: 'ASSIGN_SAME_DEST_PULSE'; toBucketId: string }
  | { type: 'ADVANCE' }
  | { type: 'CLEAR_PULSE' }
  | { type: 'UNDO_WITHIN' }
  | { type: 'UNDO_AFTER' }
  | { type: 'MUTATION_ERROR' }
  | { type: 'SKIP'; max: number }
  | { type: 'PREV' }
  | { type: 'RESET_INDEX_FOR_QUEUE_SHRINK'; queueLength: number };

const initialState: State = {
  currentIndex: 0,
  totalAssigned: 0,
  lastTappedBucketId: null,
  lastOp: null,
};

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'ASSIGN_BEGIN':
      return {
        ...state,
        lastOp: action.lastOp,
        lastTappedBucketId: action.toBucketId,
        totalAssigned: state.totalAssigned + 1,
      };
    case 'ASSIGN_REPLACE_BEGIN':
      // Double-tap: previous op rolled back imperatively before dispatch.
      // totalAssigned unchanged (we already counted it on the first tap).
      return {
        ...state,
        lastOp: action.lastOp,
        lastTappedBucketId: action.toBucketId,
      };
    case 'ASSIGN_SAME_DEST_PULSE':
      return { ...state, lastTappedBucketId: action.toBucketId };
    case 'ADVANCE':
      // No-op: useMoveTracks.applyOptimisticMove already removed the assigned
      // track from the bucket-tracks query cache synchronously, so the queue
      // shrunk by 1 and currentIndex now points at the natural next track.
      // Incrementing here would skip ONE track per assign. The reducer keeps
      // the action so reducer-mechanic tests can still observe pendingTimer
      // lifecycle via the mutation's success/error path. UNDO_AFTER uses
      // lastOp.trackIndex (captured at assign time) to restore the right index.
      return state;
    case 'CLEAR_PULSE':
      return { ...state, lastTappedBucketId: null };
    case 'UNDO_WITHIN':
      return {
        ...state,
        lastOp: null,
        lastTappedBucketId: null,
        totalAssigned: Math.max(0, state.totalAssigned - 1),
      };
    case 'UNDO_AFTER':
      if (!state.lastOp) return state;
      return {
        ...state,
        currentIndex: state.lastOp.trackIndex,
        lastOp: null,
        lastTappedBucketId: null,
        totalAssigned: Math.max(0, state.totalAssigned - 1),
      };
    case 'MUTATION_ERROR':
      return {
        ...state,
        lastOp: null,
        lastTappedBucketId: null,
        totalAssigned: Math.max(0, state.totalAssigned - 1),
      };
    case 'SKIP':
      return { ...state, currentIndex: Math.min(action.max, state.currentIndex + 1) };
    case 'PREV':
      return { ...state, currentIndex: Math.max(0, state.currentIndex - 1) };
    case 'RESET_INDEX_FOR_QUEUE_SHRINK':
      if (state.currentIndex >= action.queueLength) {
        return { ...state, currentIndex: Math.max(0, action.queueLength - 1) };
      }
      return state;
    default:
      return state;
  }
}

export const PENDING_ADVANCE_MS = 200;
export const PULSE_MS = 80;

export function useCurateSession({
  blockId,
  bucketId,
  styleId,
}: UseCurateSessionArgs): CurateSession {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const blockQuery = useTriageBlock(blockId);
  const tracksQuery = useBucketTracks(blockId, bucketId, '');
  const moveMutation = useMoveTracks(blockId, styleId);

  const [state, dispatch] = useReducer(reducer, initialState);
  const pendingTimerRef = useRef<number | null>(null);
  const pulseTimerRef = useRef<number | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  const queue: BucketTrack[] = useMemo(
    () => tracksQuery.data?.pages.flatMap((p) => p.items) ?? [],
    [tracksQuery.data],
  );
  const currentTrack = queue[state.currentIndex] ?? null;

  const destinations = useMemo<TriageBucket[]>(() => {
    if (!blockQuery.data) return [];
    return blockQuery.data.buckets.filter((b) => b.id !== bucketId);
  }, [blockQuery.data, bucketId]);

  const status: CurateStatus = useMemo(() => {
    if (blockQuery.isError || tracksQuery.isError) return 'error';
    if (blockQuery.isLoading || tracksQuery.isLoading) return 'loading';
    const noMore = !tracksQuery.hasNextPage;
    if (queue.length === 0 && noMore) return 'empty';
    if (state.currentIndex >= queue.length && noMore) return 'empty';
    return 'active';
  }, [
    blockQuery.isError,
    blockQuery.isLoading,
    tracksQuery.isError,
    tracksQuery.isLoading,
    tracksQuery.hasNextPage,
    queue.length,
    state.currentIndex,
  ]);

  // Pagination buffer
  useEffect(() => {
    if (
      tracksQuery.hasNextPage &&
      !tracksQuery.isFetchingNextPage &&
      state.currentIndex >= queue.length - 5
    ) {
      tracksQuery.fetchNextPage();
    }
  }, [
    state.currentIndex,
    queue.length,
    tracksQuery.hasNextPage,
    tracksQuery.isFetchingNextPage,
    tracksQuery.fetchNextPage,
  ]);

  // Queue-shrink reset (e.g. cache invalidation external to a session move)
  useEffect(() => {
    dispatch({ type: 'RESET_INDEX_FOR_QUEUE_SHRINK', queueLength: queue.length });
  }, [queue.length]);

  const cleanupTimers = useCallback(() => {
    if (pendingTimerRef.current !== null) {
      clearTimeout(pendingTimerRef.current);
      pendingTimerRef.current = null;
    }
    if (pulseTimerRef.current !== null) {
      clearTimeout(pulseTimerRef.current);
      pulseTimerRef.current = null;
    }
  }, []);

  // Cleanup on unmount only
  useEffect(() => () => cleanupTimers(), [cleanupTimers]);

  const schedulePulse = useCallback(() => {
    if (pulseTimerRef.current !== null) clearTimeout(pulseTimerRef.current);
    pulseTimerRef.current = window.setTimeout(() => {
      pulseTimerRef.current = null;
      dispatch({ type: 'CLEAR_PULSE' });
    }, PULSE_MS);
  }, []);

  const scheduleAdvance = useCallback(() => {
    if (pendingTimerRef.current !== null) clearTimeout(pendingTimerRef.current);
    pendingTimerRef.current = window.setTimeout(() => {
      pendingTimerRef.current = null;
      dispatch({ type: 'ADVANCE' });
    }, PENDING_ADVANCE_MS);
  }, []);

  const emitErrorToast = useCallback(
    (err: unknown) => {
      const apiErr = err instanceof ApiError ? err : null;
      const code = apiErr?.code ?? '';
      let messageKey = 'curate.toast.move_failed';
      if (apiErr?.status === 503) messageKey = 'curate.toast.service_unavailable';
      else if (code === 'tracks_not_in_source') messageKey = 'curate.toast.skip_stale';
      else if (code === 'block_not_editable') messageKey = 'curate.toast.block_finalized';
      else if (code === 'triage_block_not_found') messageKey = 'curate.toast.block_not_found';
      else if (code === 'target_bucket_inactive') messageKey = 'curate.toast.destination_inactive';
      notifications.show({
        message: t(messageKey),
        color: code === 'tracks_not_in_source' ? 'blue' : apiErr?.status === 503 ? 'yellow' : 'red',
        autoClose: 4000,
      });
    },
    [t],
  );

  const { mutate: moveMutate } = moveMutation;
  const fireMutation = useCallback(
    (input: MoveInput) => {
      moveMutate(input, {
        onSuccess: () => {
          writeLastCurateLocation(styleId, blockId, bucketId);
          writeLastCurateStyle(styleId);
        },
        onError: (err) => {
          if (pendingTimerRef.current !== null) {
            clearTimeout(pendingTimerRef.current);
            pendingTimerRef.current = null;
          }
          dispatch({ type: 'MUTATION_ERROR' });
          emitErrorToast(err);
        },
      });
    },
    [moveMutate, blockId, bucketId, styleId, emitErrorToast],
  );

  const assign = useCallback(
    (toBucketId: string) => {
      const track = queue[stateRef.current.currentIndex] ?? null;
      if (!track) return;
      if (toBucketId === bucketId) return;

      const lastOp = stateRef.current.lastOp;
      const isPending = pendingTimerRef.current !== null;

      // Same destination during pending window — only restart the timer + pulse.
      if (isPending && lastOp && lastOp.input.toBucketId === toBucketId) {
        scheduleAdvance();
        schedulePulse();
        dispatch({ type: 'ASSIGN_SAME_DEST_PULSE', toBucketId });
        return;
      }

      // Different destination during pending window — undo first.
      if (isPending && lastOp) {
        if (pendingTimerRef.current !== null) {
          clearTimeout(pendingTimerRef.current);
          pendingTimerRef.current = null;
        }
        // Fire-and-forget: rollback restores cache synchronously, inverse HTTP is async.
        void undoMoveDirect(qc, blockId, styleId, lastOp.input, lastOp.snapshot).catch(() => {
          /* if the inverse fails we re-apply the optimistic — see undoMoveDirect */
        });
        // Reuse the SAME track that the first tap was for — `queue[currentIndex]`
        // would point at the next track now (post-rollback the original is at
        // lastOp.trackIndex; the closure's `queue` is stale anyway). User intent
        // is "change destination of THIS track I just tapped".
        const replayTrackId = lastOp.input.trackIds[0] ?? track.track_id;
        const input: MoveInput = {
          fromBucketId: bucketId,
          toBucketId,
          trackIds: [replayTrackId],
        };
        const snapshot = takeSnapshot(qc, blockId, bucketId);
        scheduleAdvance();
        schedulePulse();
        dispatch({
          type: 'ASSIGN_REPLACE_BEGIN',
          toBucketId,
          lastOp: { input, snapshot, trackIndex: lastOp.trackIndex },
        });
        fireMutation(input);
        return;
      }

      // Fresh assignment.
      const input: MoveInput = {
        fromBucketId: bucketId,
        toBucketId,
        trackIds: [track.track_id],
      };
      const snapshot = takeSnapshot(qc, blockId, bucketId);
      scheduleAdvance();
      schedulePulse();
      dispatch({
        type: 'ASSIGN_BEGIN',
        toBucketId,
        lastOp: { input, snapshot, trackIndex: stateRef.current.currentIndex },
      });
      fireMutation(input);
    },
    [
      queue,
      bucketId,
      blockId,
      styleId,
      qc,
      scheduleAdvance,
      schedulePulse,
      fireMutation,
    ],
  );

  const undo = useCallback(() => {
    const lastOp = stateRef.current.lastOp;
    if (!lastOp) return;
    const isPending = pendingTimerRef.current !== null;

    if (isPending) {
      clearTimeout(pendingTimerRef.current as number);
      pendingTimerRef.current = null;
      if (pulseTimerRef.current !== null) {
        clearTimeout(pulseTimerRef.current);
        pulseTimerRef.current = null;
      }
      void undoMoveDirect(qc, blockId, styleId, lastOp.input, lastOp.snapshot).catch(() => {});
      dispatch({ type: 'UNDO_WITHIN' });
    } else {
      void undoMoveDirect(qc, blockId, styleId, lastOp.input, lastOp.snapshot).catch(() => {});
      dispatch({ type: 'UNDO_AFTER' });
    }
  }, [qc, blockId, styleId]);

  const skip = useCallback(() => {
    dispatch({ type: 'SKIP', max: queue.length });
  }, [queue.length]);

  const prev = useCallback(() => {
    dispatch({ type: 'PREV' });
  }, []);

  const openSpotify = useCallback(() => {
    if (currentTrack?.spotify_id) {
      window.open(
        `https://open.spotify.com/track/${currentTrack.spotify_id}`,
        '_blank',
        'noopener,noreferrer',
      );
    }
  }, [currentTrack]);

  return {
    status,
    queue,
    currentTrack,
    currentIndex: state.currentIndex,
    totalAssigned: state.totalAssigned,
    destinations,
    block: blockQuery.data ?? null,
    lastTappedBucketId: state.lastTappedBucketId,
    canUndo: state.lastOp !== null,
    assign,
    undo,
    skip,
    prev,
    openSpotify,
  };
}
