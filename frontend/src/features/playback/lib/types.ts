export type QueueStatus =
  | 'idle'
  | 'loading'
  | 'playing'
  | 'paused'
  | 'buffering'
  | 'ended'
  | 'error'
  | 'disconnected';

export type SdkErrorKind =
  | 'init'
  | 'auth'
  | 'account'
  | 'playback'
  | 'transient';

export interface SdkError {
  kind: SdkErrorKind;
  message: string;
}

export interface PlaybackTrack {
  id: string;
  title: string;
  artists: string;
  cover_url: string | null;
  duration_ms: number;
  spotify_id: string | null;
}

export type QueueSource =
  | { type: 'bucket'; blockId: string; bucketId: string }
  | { type: 'category'; categoryId: string; styleId: string }
  | { type: 'playlist'; playlistId: string };

export interface BindQueueArgs {
  source: QueueSource;
  tracks: readonly PlaybackTrack[];
  cursor: number;
  onCursorChange: (next: number) => void;
}

export type FsmAction =
  | { type: 'PLAY_REQUESTED' }
  | { type: 'SDK_PLAYING' }
  | { type: 'PAUSE' }
  | { type: 'RESUME' }
  | { type: 'BUFFER_START' }
  | { type: 'BUFFER_END' }
  | { type: 'END' }
  | { type: 'SDK_ERROR' }
  | { type: 'RETRY' }
  | { type: 'CLEAR' };
