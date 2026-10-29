import { useLocalStorage } from '@mantine/hooks';

export type ScrubberMode = 'waveform' | 'progress';

/** The player's scrub bar, per device: the waveform (default) or a plain progress bar. */
export function usePlayerScrubber() {
  return useLocalStorage<ScrubberMode>({
    key: 'clouder.player_scrubber',
    defaultValue: 'waveform',
    getInitialValueInEffect: false,
  });
}
