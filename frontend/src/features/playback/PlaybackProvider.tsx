import {
  createContext,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from 'react';
import type {
  BindQueueArgs,
  PlaybackTrack,
  QueueSource,
  QueueStatus,
  SdkError,
} from './lib/types';

export interface PlaybackContextValue {
  queue: {
    source: QueueSource | null;
    tracks: readonly PlaybackTrack[];
    cursor: number;
    status: QueueStatus;
  };
  track: {
    current: PlaybackTrack | null;
    positionMs: number;
    durationMs: number;
  };
  sdk: { ready: boolean; error: SdkError | null };
  controls: {
    play: (idx?: number) => Promise<void>;
    pause: () => Promise<void>;
    togglePlayPause: () => Promise<void>;
    next: () => Promise<void>;
    prev: () => Promise<void>;
    seekMs: (ms: number) => Promise<void>;
    seekPct: (p: number) => Promise<void>;
    bindQueue: (b: BindQueueArgs) => void;
    clearQueue: () => void;
    cancelPendingAdvance: () => void;
    openSpotifyExternal: (uri: string) => void;
  };
}

export const PlaybackContext = createContext<PlaybackContextValue | null>(null);

interface State {
  queue: PlaybackContextValue['queue'];
  track: PlaybackContextValue['track'];
  sdk: PlaybackContextValue['sdk'];
}

const INITIAL_STATE: State = {
  queue: { source: null, tracks: [], cursor: 0, status: 'idle' },
  track: { current: null, positionMs: 0, durationMs: 0 },
  sdk: { ready: false, error: null },
};

type Action = { type: 'noop' };

function reducer(state: State, _action: Action): State {
  return state;
}

export function PlaybackProvider({ children }: { children: ReactNode }) {
  const [state] = useReducer(reducer, INITIAL_STATE);
  const onCursorChangeRef = useRef<((next: number) => void) | null>(null);

  const value = useMemo<PlaybackContextValue>(
    () => ({
      queue: state.queue,
      track: state.track,
      sdk: state.sdk,
      controls: {
        play: async () => {},
        pause: async () => {},
        togglePlayPause: async () => {},
        next: async () => {},
        prev: async () => {},
        seekMs: async () => {},
        seekPct: async () => {},
        bindQueue: (args) => {
          onCursorChangeRef.current = args.onCursorChange;
        },
        clearQueue: () => {},
        cancelPendingAdvance: () => {},
        openSpotifyExternal: (uri) => {
          window.open(
            uri.replace('spotify:track:', 'https://open.spotify.com/track/'),
            '_blank',
            'noopener',
          );
        },
      },
    }),
    [state],
  );

  return <PlaybackContext.Provider value={value}>{children}</PlaybackContext.Provider>;
}
