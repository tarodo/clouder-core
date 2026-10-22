import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { components } from '../../../api/schema';

export type YoutubeReview = components['schemas']['YoutubeReview'];
export type YoutubeReviewTrack = YoutubeReview['tracks'][number];

export interface ReviewCell {
  styleId: number;
  weekYear: number;
  weekNumber: number;
}

const reviewKey = (c: ReviewCell) => ['admin', 'youtube-review', c.styleId, c.weekYear, c.weekNumber];

export function useYoutubeReview(cell: ReviewCell) {
  return useQuery({
    queryKey: reviewKey(cell),
    queryFn: () =>
      api<YoutubeReview>(
        `/admin/youtube/review?style_id=${cell.styleId}&week_year=${cell.weekYear}` +
          `&week_number=${cell.weekNumber}`,
      ),
  });
}

export type ResolveVars =
  | { trackId: string; action: 'accept'; vendorTrackId: string }
  | { trackId: string; action: 'reject' };

/** Accept a candidate or mark the track as not on YouTube; the track leaves the list. */
export function useResolveYoutubeReview(cell: ReviewCell) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: ResolveVars) =>
      api(`/admin/youtube/review/${encodeURIComponent(vars.trackId)}`, {
        method: 'POST',
        body: JSON.stringify(
          vars.action === 'accept'
            ? { action: 'accept', vendor_track_id: vars.vendorTrackId }
            : { action: 'reject' },
        ),
      }),
    onSuccess: (_data, vars) => {
      qc.setQueryData<YoutubeReview>(reviewKey(cell), (old) =>
        old ? { ...old, tracks: old.tracks.filter((t) => t.track_id !== vars.trackId) } : old,
      );
      void qc.invalidateQueries({ queryKey: ['admin', 'coverage'] });
    },
  });
}
