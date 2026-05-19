import { Container, Stack, Title } from '@mantine/core';
import { useParams, useSearchParams, Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useLabelsList } from '../hooks/useLabelsList';
import { EntityTabs } from '../components/EntityTabs';
import { LibraryFilters } from '../components/LibraryFilters';
import { LabelListGrid } from '../components/LabelListGrid';

export function LibraryListPage() {
  const { t } = useTranslation();
  const { styleId } = useParams<{ styleId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();

  const q = searchParams.get('q') ?? '';
  const rawSort = searchParams.get('sort');
  const sort: 'name' | 'recent' = rawSort === 'recent' ? 'recent' : 'name';

  const query = useLabelsList({ styleId: styleId ?? '', q, sort });

  if (!styleId) return <Navigate to="/library" replace />;
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next, { replace: true });
  };

  return (
    <Container size="lg" py="md">
      <Stack gap="md">
        <Title order={2}>{t('library.list.title')}</Title>
        <EntityTabs active="labels" styleId={styleId} />
        <LibraryFilters
          q={q}
          sort={sort}
          onQChange={(v) => updateParam('q', v)}
          onSortChange={(v) => updateParam('sort', v)}
        />
        <LabelListGrid
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
