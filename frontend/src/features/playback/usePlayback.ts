import { useContext } from 'react';
import { PlaybackContext, type PlaybackContextValue } from './PlaybackProvider';

export function usePlayback(): PlaybackContextValue {
  const ctx = useContext(PlaybackContext);
  if (!ctx) throw new Error('usePlayback must be used inside <PlaybackProvider>');
  return ctx;
}
