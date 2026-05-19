import { Container, Stack, Title } from '@mantine/core';
import { useParams, useSearchParams, Navigate, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useMemo } from 'react';
import { useLabelsList } from '../hooks/useLabelsList';
import { EntityTabs } from '../components/EntityTabs';
import { LibraryFilters, type StyleOption } from '../components/LibraryFilters';
import { LabelsTable } from '../components/LabelsTable';
import { useStyles } from '../../../hooks/useStyles';
import { slugifyStyle } from '../lib/slugifyStyle';

export function LibraryListPage() {
  const { t } = useTranslation();
  const { styleId } = useParams<{ styleId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const q = searchParams.get('q') ?? '';
  const rawSort = searchParams.get('sort');
  const sort: 'name' | 'recent' = rawSort === 'recent' ? 'recent' : 'name';

  const stylesQuery = useStyles();
  const styleOptions: ReadonlyArray<StyleOption> = useMemo(
    () =>
      stylesQuery.data?.items.map((s) => ({
        value: slugifyStyle(s.name),
        label: s.name,
      })) ?? [],
    [stylesQuery.data],
  );
  const query = useLabelsList({ styleId: styleId ?? '', q, sort });

  if (!styleId) return <Navigate to="/library" replace />;
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next, { replace: true });
  };

  const onStyleChange = (nextSlug: string) => {
    if (nextSlug === styleId) return;
    const qs = searchParams.toString();
    navigate(`/library/${nextSlug}${qs ? `?${qs}` : ''}`);
  };

  return (
    <Container size="xl" py="md">
      <Stack gap="md">
        <Title order={2}>{t('library.list.title')}</Title>
        <EntityTabs active="labels" styleId={styleId} />
        <LibraryFilters
          q={q}
          sort={sort}
          styleId={styleId}
          styleOptions={styleOptions}
          stylesLoading={stylesQuery.isLoading}
          onQChange={(v) => updateParam('q', v)}
          onSortChange={(v) => updateParam('sort', v)}
          onStyleChange={onStyleChange}
        />
        <LabelsTable
          items={items}
          styleId={styleId}
          isLoading={query.isLoading}
          hasNextPage={!!query.hasNextPage}
          isFetchingNextPage={query.isFetchingNextPage}
          onLoadMore={() => query.fetchNextPage()}
        />
      </Stack>
    </Container>
  );
}
