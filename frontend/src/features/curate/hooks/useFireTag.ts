import { useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { api } from '../../../api/client';
import { tagsKey, type Tag } from '../../tags/hooks/useTags';
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

/** Server-side lookup: the cached vocabulary may be stale or truncated. */
async function findOrCreateFireTag(): Promise<{ id: string; created: boolean }> {
  const found = await api<{ items: Tag[] }>(
    `/tags?search=${encodeURIComponent(FIRE_TAG_NAME)}&limit=50&offset=0`,
  );
  const tag = found.items.find(isFire);
  if (tag) return { id: tag.id, created: false };
  const made = await api<Tag>('/tags', {
    method: 'POST',
    body: JSON.stringify({ name: FIRE_TAG_NAME, color: FIRE_TAG_COLOR }),
  });
  return { id: made.id, created: true };
}

export interface UseFireTagResult {
  /** The current track carries the fire tag (optimistic while a toggle is in flight). */
  active: boolean;
  /** The track's tag set has loaded; toggling before that is a no-op. */
  ready: boolean;
  toggle: () => void;
}

interface Vars {
  trackId: string;
  on: boolean;
  current: TrackTag[];
}

export function useFireTag(trackId: string | null): UseFireTagResult {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const trackTags = useQuery({
    queryKey: trackTagsKey(trackId ?? ''),
    queryFn: async () => (await api<{ tags: TrackTag[] }>(`/tracks/${trackId}/tags`)).tags,
    enabled: !!trackId,
  });
  // Per-track refs, not mutation.isPending: two key presses in one tick both
  // see isPending=false and would create the tag twice.
  const inFlight = useRef(new Set<string>());

  const mutation = useMutation<TrackTag[], Error, Vars, { prev: TrackTag[] }>({
    mutationFn: async ({ trackId: id, on, current }) => {
      if (!on) {
        const tag = current.find(isFire);
        if (tag) await api(`/tracks/${id}/tags/${tag.id}`, { method: 'DELETE' });
        return current.filter((x) => !isFire(x));
      }
      const tag = await findOrCreateFireTag();
      if (tag.created) void qc.invalidateQueries({ queryKey: tagsKey() });
      const res = await api<{ tags: TrackTag[] }>(`/tracks/${id}/tags`, {
        method: 'POST',
        body: JSON.stringify({ tag_id: tag.id }),
      });
      return res.tags.map(({ id: tagId, name, color }) => ({ id: tagId, name, color }));
    },
    onMutate: async ({ trackId: id, on, current }) => {
      // A late refetch must not overwrite the optimistic state.
      await qc.cancelQueries({ queryKey: trackTagsKey(id) });
      const next = on
        ? [...current, { id: 'fire-pending', name: FIRE_TAG_NAME, color: FIRE_TAG_COLOR }]
        : current.filter((x) => !isFire(x));
      qc.setQueryData(trackTagsKey(id), next);
      return { prev: current };
    },
    // Real ids from the server, so a quick second press deletes the right tag.
    onSuccess: (tags, { trackId: id }) => qc.setQueryData(trackTagsKey(id), tags),
    onError: (_err, { trackId: id }, ctx) => {
      if (ctx) qc.setQueryData(trackTagsKey(id), ctx.prev);
      void qc.invalidateQueries({ queryKey: trackTagsKey(id) });
      notifications.show({ message: t('tags.toast.update_failed'), color: 'red' });
    },
    onSettled: (_d, _e, { trackId: id }) => {
      inFlight.current.delete(id);
      // Category track lists embed tags; refresh any that are mounted.
      void qc.invalidateQueries({ queryKey: ['categories', 'tracks'] });
    },
  });

  const current = trackTags.data;
  const active = current?.some(isFire) ?? false;

  const toggle = () => {
    if (!trackId || !current || inFlight.current.has(trackId)) return;
    inFlight.current.add(trackId);
    mutation.mutate({ trackId, on: !active, current });
  };

  return { active, ready: current !== undefined, toggle };
}
