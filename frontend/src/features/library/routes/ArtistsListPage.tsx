import { Container, Stack } from '@mantine/core';
import { useParams, useSearchParams, Navigate, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useMemo } from 'react';
import { useArtistsList, type ArtistsListMy } from '../hooks/useArtistsList';
import { EntityTabs } from '../components/EntityTabs';
import { LibraryFilters, type StyleOption } from '../components/LibraryFilters';
import { ArtistsTable } from '../components/ArtistsTable';
import { useStyles } from '../../../hooks/useStyles';
import { PageHeader } from '../../../components/PageHeader';
import { slugifyStyle } from '../lib/slugifyStyle';

const PAGE_SIZE = 25;

const MY_VALUES: ReadonlySet<ArtistsListMy> = new Set(['all', 'liked', 'disliked', 'unrated']);

function readMy(raw: string | null): ArtistsListMy {
  if (raw && MY_VALUES.has(raw as ArtistsListMy)) return raw as ArtistsListMy;
  return 'all';
}

export function ArtistsListPage() {
  const { t } = useTranslation();
  const { styleId } = useParams<{ styleId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const q = searchParams.get('q') ?? '';
  const rawSort = searchParams.get('sort');
  const sort: 'name' | 'recent' = rawSort === 'recent' ? 'recent' : 'name';
  const pageParam = Number(searchParams.get('page') ?? '1');
  const page = Number.isFinite(pageParam) && pageParam > 0 ? pageParam : 1;
  const my = readMy(searchParams.get('my'));

  const stylesQuery = useStyles();
  const styleOptions: ReadonlyArray<StyleOption> = useMemo(
    () =>
      stylesQuery.data?.items.map((s) => ({
        value: slugifyStyle(s.name),
        label: s.name,
      })) ?? [],
    [stylesQuery.data],
  );
  const query = useArtistsList({
    styleId: styleId ?? '',
    q,
    sort,
    page,
    limit: PAGE_SIZE,
    my,
  });

  if (!styleId) return <Navigate to="/library" replace />;
  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const updateParam = (key: string, value: string, resetPage = false) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    if (resetPage) next.delete('page');
    setSearchParams(next, { replace: true });
  };

  const onStyleChange = (nextSlug: string) => {
    if (nextSlug === styleId) return;
    const next = new URLSearchParams(searchParams);
    next.delete('page');
    const qs = next.toString();
    navigate(`/library/${nextSlug}/artists${qs ? `?${qs}` : ''}`);
  };

  const onPageChange = (nextPage: number) => {
    const next = new URLSearchParams(searchParams);
    if (nextPage <= 1) next.delete('page');
    else next.set('page', String(nextPage));
    setSearchParams(next, { replace: false });
  };

  return (
    <Container size="xl" py="md">
      <Stack gap="md">
        <PageHeader title={t('library.artists_list.title')}>
          <EntityTabs active="artists" styleId={styleId} />
        </PageHeader>
        <LibraryFilters
          q={q}
          sort={sort}
          styleId={styleId}
          styleOptions={styleOptions}
          stylesLoading={stylesQuery.isLoading}
          my={my}
          onQChange={(v) => updateParam('q', v, true)}
          onSortChange={(v) => updateParam('sort', v, true)}
          onStyleChange={onStyleChange}
          onMyChange={(v) => updateParam('my', v === 'all' ? '' : v, true)}
        />
        <ArtistsTable
          items={items}
          isLoading={query.isLoading}
          page={page}
          pageCount={pageCount}
          onPageChange={onPageChange}
        />
      </Stack>
    </Container>
  );
}
