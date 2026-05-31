import { useCallback, useEffect, useMemo, useState } from 'react';
import { Anchor, Breadcrumbs, Flex, Stack, useMantineTheme } from '@mantine/core';
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import {
  Link,
  Navigate,
  Outlet,
  useMatch,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { useCategoryDetail } from '../hooks/useCategoryDetail';
import { useRenameCategory } from '../hooks/useRenameCategory';
import { useDeleteCategory } from '../hooks/useDeleteCategory';
import {
  useCategoryTracks,
  type CategoryTrack,
  type CategoryTrackSort,
  type SortOrder,
} from '../hooks/useCategoryTracks';
import { useCategoryPlayerQueue } from '../hooks/useCategoryPlayerQueue';
import { CategoryFormDialog } from '../components/CategoryFormDialog';
import { CategoryDetailHeader } from '../components/CategoryDetailHeader';
import { CategoryPlayerPanel } from '../components/CategoryPlayerPanel';
import { TracksTab } from '../components/TracksTab';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { EmptyState } from '../../../components/EmptyState';
import { usePlayback } from '../../playback/usePlayback';
import type { PlaybackTrack } from '../../playback/lib/types';
import { readTagsUrlState } from '../../tags';
import { readFresh } from '../lib/freshUrlState';

function toPlaybackTrack(t: CategoryTrack): PlaybackTrack {
  return {
    id: t.id,
    title: t.title,
    artists: t.artists.map((a) => a.name).join(', '),
    duration_ms: t.length_ms ?? 0,
    spotify_id: t.spotify_id,
    cover_url: null,
  };
}

export type CategoryDetailOutletContext = {
  items: CategoryTrack[];
};

export function CategoryDetailPage() {
  const { styleId, id } = useParams<{ styleId: string; id: string }>();
  if (!styleId || !id) return <Navigate to="/categories" replace />;
  return <CategoryDetailPageInner styleId={styleId} id={id} />;
}

function CategoryDetailPageInner({ styleId, id }: { styleId: string; id: string }) {
  const navigate = useNavigate();
  const { t } = useTranslation();

  const { data, isLoading, isError, error } = useCategoryDetail(id);
  const renameMut = useRenameCategory(id, styleId);
  const deleteMut = useDeleteCategory(styleId);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameServerError, setRenameServerError] = useState<string | undefined>();

  const playback = usePlayback();
  const theme = useMantineTheme();
  const isDesktop = useMediaQuery(`(min-width: ${theme.breakpoints.md})`);
  // Mobile uses a fullscreen player route nested under this one. When the
  // nested /player route is active, render <Outlet> instead of the
  // split/single layout — but parent stays mounted so queue + filter state
  // survive the navigation.
  const onPlayerSubpath = useMatch(
    { path: '/categories/:styleId/:id/player', end: false },
  );

  // Filter state hoisted from TracksTab so the queue binding can mirror what
  // the user actually sees (search + sort + tags + fresh). URL state owns
  // tags + fresh; rawSearch + sort live here.
  const [searchParams] = useSearchParams();
  const tagFilter = readTagsUrlState(searchParams);
  const fresh = readFresh(searchParams);
  const [rawSearch, setRawSearch] = useState('');
  const [debounced] = useDebouncedValue(rawSearch.trim().toLowerCase(), 300);
  const [sortKey, setSortKey] = useState<CategoryTrackSort>('added_at');
  const [sortDir, setSortDir] = useState<SortOrder>('desc');

  // Pre-warm SDK on mount so first play happens inside the user-gesture window.
  useEffect(() => {
    void playback.controls.prewarm();
  }, [playback.controls]);

  const tracksQuery = useCategoryTracks(
    id,
    debounced,
    sortKey,
    sortDir,
    tagFilter.selectedIds,
    tagFilter.match,
    fresh,
  );

  const items: CategoryTrack[] = useMemo(
    () => tracksQuery.data?.pages.flatMap((p) => p.items) ?? [],
    [tracksQuery.data],
  );
  const playerTracks = useMemo<PlaybackTrack[]>(
    () => items.map(toPlaybackTrack),
    [items],
  );
  useCategoryPlayerQueue(id, styleId, playerTracks);

  const playTrack = useCallback(
    (track: CategoryTrack) => {
      if (!track.spotify_id) return;
      void playback.controls.prewarm();
      const queueIdx = playback.queue.tracks.findIndex((q) => q.id === track.id);
      if (queueIdx >= 0) {
        void playback.controls.play(queueIdx);
      } else {
        void playback.controls.play(undefined, toPlaybackTrack(track));
      }
      if (!isDesktop) {
        navigate(`/categories/${styleId}/${id}/player`);
      }
    },
    [playback.controls, playback.queue.tracks, isDesktop, navigate, styleId, id],
  );

  if (isLoading) return <FullScreenLoader />;
  if (isError) {
    if (error instanceof ApiError && error.status === 404) {
      return (
        <EmptyState
          title={t('errors.not_found')}
          body={
            <Anchor component={Link} to={`/categories/${styleId}`}>
              {t('categories.detail.back_to_list')}
            </Anchor>
          }
        />
      );
    }
    return <EmptyState title={t('errors.unknown')} body={t('errors.server_error')} />;
  }
  if (!data) return null;

  const trackCountLabel = t('categories.track_count', { count: data.track_count });

  function openDelete() {
    if (!data) return;
    modals.openConfirmModal({
      title: t('categories.delete_modal.title'),
      children: t('categories.delete_modal.body', { name: data.name }),
      labels: { confirm: t('categories.delete_modal.confirm'), cancel: t('categories.delete_modal.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await deleteMut.mutateAsync(id!);
          notifications.show({ message: t('categories.toast.deleted'), color: 'green' });
          navigate(`/categories/${styleId}`);
        } catch {
          notifications.show({ message: t('categories.toast.generic_error'), color: 'red' });
        }
      },
    });
  }

  async function handleRename(input: { name: string }) {
    setRenameServerError(undefined);
    try {
      await renameMut.mutateAsync(input);
      notifications.show({ message: t('categories.toast.renamed'), color: 'green' });
      setRenameOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setRenameServerError(t('categories.errors.name_conflict'));
      } else {
        notifications.show({ message: t('categories.toast.generic_error'), color: 'red' });
      }
    }
  }

  // When the nested /player route is active (mobile only), render just the
  // outlet — the queue + filter state above already includes the user's
  // visible list, so the player has the right context. Items are forwarded
  // via outlet context so the child page can pass them to CategoryPlayerPanel
  // for rich metadata (label/BPM/mix_name) lookup.
  if (onPlayerSubpath) {
    return <Outlet context={{ items } satisfies CategoryDetailOutletContext} />;
  }

  const tracksTab = (
    <TracksTab
      categoryId={id}
      styleId={styleId}
      items={items}
      total={tracksQuery.data?.pages[0]?.total ?? 0}
      isLoading={tracksQuery.isLoading}
      hasNextPage={!!tracksQuery.hasNextPage}
      isFetchingNextPage={tracksQuery.isFetchingNextPage}
      fetchNextPage={tracksQuery.fetchNextPage}
      rawSearch={rawSearch}
      setRawSearch={setRawSearch}
      debounced={debounced}
      sortKey={sortKey}
      sortDir={sortDir}
      setSortKey={setSortKey}
      setSortDir={setSortDir}
      onPlay={playTrack}
      currentTrackId={playback.track.current?.id ?? null}
      playing={playback.queue.status === 'playing'}
      onTogglePlay={playback.controls.togglePlayPause}
    />
  );

  return (
    <Stack gap="lg">
      <Breadcrumbs>
        <Anchor component={Link} to="/categories">
          {t('categories.page_title')}
        </Anchor>
        <Anchor component={Link} to={`/categories/${styleId}`}>
          {data.style_name}
        </Anchor>
      </Breadcrumbs>
      <CategoryDetailHeader
        name={data.name}
        trackCountLabel={trackCountLabel}
        onRename={() => setRenameOpen(true)}
        onDelete={openDelete}
      />
      {isDesktop ? (
        <Flex gap="lg" align="flex-start" wrap="nowrap">
          <CategoryPlayerPanel categoryId={id} styleId={styleId} items={items} />
          <div style={{ flex: 1, minWidth: 0 }}>{tracksTab}</div>
        </Flex>
      ) : (
        tracksTab
      )}
      <CategoryFormDialog
        mode="rename"
        opened={renameOpen}
        initialName={data.name}
        submitting={renameMut.isPending}
        onClose={() => {
          setRenameOpen(false);
          setRenameServerError(undefined);
        }}
        onSubmit={handleRename}
        serverError={renameServerError}
      />
    </Stack>
  );
}
