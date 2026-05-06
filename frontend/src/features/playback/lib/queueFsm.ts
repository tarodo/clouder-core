import type { QueueStatus, FsmAction } from './types';

export function transition(status: QueueStatus, action: FsmAction): QueueStatus {
  switch (action.type) {
    case 'PLAY_REQUESTED':
      return status === 'error' ? 'error' : 'loading';
    case 'SDK_PLAYING':
      return 'playing';
    case 'PAUSE':
      return status === 'playing' || status === 'buffering' ? 'paused' : status;
    case 'RESUME':
      return status === 'paused' ? 'playing' : status;
    case 'BUFFER_START':
      return status === 'playing' ? 'buffering' : status;
    case 'BUFFER_END':
      return status === 'buffering' ? 'playing' : status;
    case 'END':
      return status === 'error' ? 'error' : 'ended';
    case 'SDK_ERROR':
      return 'error';
    case 'RETRY':
      return status === 'error' ? 'loading' : status;
    case 'CLEAR':
      return 'idle';
    default:
      return status;
  }
}
