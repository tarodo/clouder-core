/**
 * The demo's music: instrumental tracks made with Suno, normalized to -14 LUFS and served
 * from `<BASE_URL>audio/` (the Pages build downloads them from the `demo-audio-v1`
 * release). Each demo track plays one clip of its style and takes that clip's length.
 */
export interface Clip {
  file: string;
  ms: number;
}

export const CLIPS: Record<string, Clip[]> = {
  's-melodic': [
    { file: 'melodic-1.mp3', ms: 194_880 },
    { file: 'melodic-2.mp3', ms: 253_640 },
    { file: 'melodic-3.mp3', ms: 313_760 },
  ],
  's-afro': [
    { file: 'afro-1.mp3', ms: 304_960 },
    { file: 'afro-2.mp3', ms: 334_160 },
    { file: 'afro-3.mp3', ms: 249_601 },
    { file: 'afro-4.mp3', ms: 249_601 },
    { file: 'afro-5.mp3', ms: 248_800 },
  ],
};

/** The clip a track plays: its style's clips, picked by the track number. */
export function clipOf(styleId: string, trackId: string): Clip | null {
  const clips = CLIPS[styleId];
  if (!clips?.length) return null;
  return clips[Number(trackId.split('-').pop()) % clips.length] ?? null;
}
