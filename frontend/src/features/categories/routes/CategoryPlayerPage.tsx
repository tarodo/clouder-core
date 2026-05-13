import { Stack, ActionIcon, Group } from '@mantine/core';
import { IconArrowLeft } from '@tabler/icons-react';
import { useNavigate, useParams, Navigate } from 'react-router';
import { useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { CategoryPlayerPanel } from '../components/CategoryPlayerPanel';
import { usePlayback } from '../../playback/usePlayback';
import { useCategoryTracks, type CategoryTrack } from '../hooks/useCategoryTracks';
import { useCategoryPlayerQueue } from '../hooks/useCategoryPlayerQueue';
import type { PlaybackTrack } from '../../playback/lib/types';

export function CategoryPlayerPage() {
  const { styleId, id } = useParams<{ styleId: string; id: string }>();
  if (!styleId || !id) return <Navigate to="/categories" replace />;
  return <CategoryPlayerPageInner styleId={styleId} id={id} />;
}

function CategoryPlayerPageInner({ styleId, id }: { styleId: string; id: string }) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const playback = usePlayback();

  useEffect(() => {
    void playback.controls.prewarm();
  }, [playback.controls]);

  const playerQuery = useCategoryTracks(id, '', 'added_at', 'desc', [], 'all', true);
  const playerTracks = useMemo<PlaybackTrack[]>(
    () =>
      (playerQuery.data?.pages ?? []).flatMap((p) =>
        p.items.map((tr: CategoryTrack) => ({
          id: tr.id,
          title: tr.title,
          artists: tr.artists.map((a) => a.name).join(', '),
          duration_ms: tr.length_ms ?? 0,
          spotify_id: tr.spotify_id,
          cover_url: null,
        })),
      ),
    [playerQuery.data],
  );
  useCategoryPlayerQueue(id, styleId, playerTracks);

  return (
    <Stack gap="md" p="md">
      <Group>
        <ActionIcon
          variant="subtle"
          onClick={() => navigate(`/categories/${styleId}/${id}`)}
          aria-label={t('category_player.actions.back_aria')}
        >
          <IconArrowLeft />
        </ActionIcon>
      </Group>
      <CategoryPlayerPanel categoryId={id} styleId={styleId} />
    </Stack>
  );
}
