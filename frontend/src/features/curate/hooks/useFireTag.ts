import { useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { fetchTags, tagsKey, type Tag } from '../../tags/hooks/useTags';
import { normalizeTagName } from '../../tags/lib/normalizeTagName';

/** The "fire" mark is an ordinary user tag; this name is how Curate finds it. */
export const FIRE_TAG_NAME = '🔥';
const FIRE_TAG_COLOR = '#f97316'; // palette orange

interface TrackTag {
  id: string;
  name: string;
  color: string | null;
}

const trackTagsKey = (trackId: string) => ['tracks', 'tags', trackId] as const;

const isFire = (t: { name: string }) => normalizeTagName(t.name) === FIRE_TAG_NAME;

export interface UseFireTagResult {
  /** The current track carries the fire tag (optimistic while a toggle is in flight). */
  active: boolean;
  /** The track's tag set has loaded; toggling before that is a no-op. */
  ready: boolean;
  toggle: () => void;
}

export function useFireTag(trackId: string | null): UseFireTagResult {
  const qc = useQueryClient();
  const trackTags = useQuery({
    queryKey: trackTagsKey(trackId ?? ''),
    queryFn: async () => (await api<{ tags: TrackTag[] }>(`/tracks/${trackId}/tags`)).tags,
    enabled: !!trackId,
  });
  // A ref, not mutation.isPending: two key presses in one tick both see
  // isPending=false and would create the tag twice.
  const inFlight = useRef(false);

  const mutation = useMutation<void, Error, { trackId: string; on: boolean; current: TrackTag[] }, { prev: TrackTag[] }>({
    mutationFn: async ({ trackId: id, on, current }) => {
      if (!on) {
        const tag = current.find(isFire);
        if (tag) await api(`/tracks/${id}/tags/${tag.id}`, { method: 'DELETE' });
        return;
      }
      const vocabulary = await qc.fetchQuery({ queryKey: tagsKey(), queryFn: fetchTags, staleTime: 60_000 });
      let tag: Pick<Tag, 'id'> | undefined = vocabulary.find(isFire);
      if (!tag) {
        tag = await api<Tag>('/tags', {
          method: 'POST',
          body: JSON.stringify({ name: FIRE_TAG_NAME, color: FIRE_TAG_COLOR }),
        });
        await qc.invalidateQueries({ queryKey: tagsKey() });
      }
      await api(`/tracks/${id}/tags`, { method: 'POST', body: JSON.stringify({ tag_id: tag.id }) });
    },
    onMutate: ({ trackId: id, on, current }) => {
      const next = on
        ? [...current, { id: 'fire-pending', name: FIRE_TAG_NAME, color: FIRE_TAG_COLOR }]
        : current.filter((t) => !isFire(t));
      qc.setQueryData(trackTagsKey(id), next);
      return { prev: current };
    },
    onError: (_err, { trackId: id }, ctx) => {
      if (ctx) qc.setQueryData(trackTagsKey(id), ctx.prev);
    },
    onSettled: (_d, _e, { trackId: id }) => {
      inFlight.current = false;
      void qc.invalidateQueries({ queryKey: trackTagsKey(id) });
      // Category track lists embed tags; refresh any that are mounted.
      void qc.invalidateQueries({ queryKey: ['categories', 'tracks'] });
    },
  });

  const current = trackTags.data;
  const active = current?.some(isFire) ?? false;

  const toggle = () => {
    if (!trackId || !current || inFlight.current) return;
    inFlight.current = true;
    mutation.mutate({ trackId, on: !active, current });
  };

  return { active, ready: current !== undefined, toggle };
}
