import { useState } from 'react';
import { Button, Group, Stack, Switch, Table, TextInput, Tooltip } from '@mantine/core';
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks';
import { IconSearch, IconSettings, IconX } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router';
import {
  useCategoryTracks,
  type CategoryTrackSort,
  type SortOrder,
} from '../hooks/useCategoryTracks';
import { TrackRow } from './TrackRow';
import { TrackRowActions } from './TrackRowActions';
import { SortableTh } from './SortableTh';
import { EmptyState } from '../../../components/EmptyState';
import {
  TagsFilterBar,
  TagsManagerModal,
  readTagsUrlState,
  writeTagsUrlState,
  type TagsFilterState,
} from '../../tags';
import { readFresh, writeFresh } from '../lib/freshUrlState';

export interface TracksTabProps {
  categoryId: string;
  styleId: string;
}

export function TracksTab({ categoryId, styleId }: TracksTabProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const [searchParams, setSearchParams] = useSearchParams();
  const tagFilter = readTagsUrlState(searchParams);
  const fresh = readFresh(searchParams);
  const setFresh = (value: boolean) => {
    setSearchParams(writeFresh(searchParams, value), { replace: true });
  };

  const [rawSearch, setRawSearch] = useState('');
  const [debounced] = useDebouncedValue(rawSearch.trim().toLowerCase(), 300);
  const [sortKey, setSortKey] = useState<CategoryTrackSort>('added_at');
  const [sortDir, setSortDir] = useState<SortOrder>('desc');
  const [managerOpen, setManagerOpen] = useState(false);

  const handleSort = (key: CategoryTrackSort) => {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'title' ? 'asc' : 'desc');
    }
  };

  const handleTagFilterChange = (next: TagsFilterState) => {
    setSearchParams(writeTagsUrlState(searchParams, next), { replace: true });
  };

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useCategoryTracks(
      categoryId,
      debounced,
      sortKey,
      sortDir,
      tagFilter.selectedIds,
      tagFilter.match,
      fresh,
    );

  const items = data?.pages.flatMap((p) => p.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;
  const remaining = Math.max(0, total - items.length);

  const filterRow = (
    <Group gap="sm" align="flex-end" wrap="wrap">
      <TextInput
        placeholder={t('categories.detail.tracks_search_placeholder')}
        leftSection={<IconSearch size={16} />}
        value={rawSearch}
        onChange={(e) => setRawSearch(e.currentTarget.value)}
        rightSection={
          rawSearch ? (
            <IconX
              size={16}
              role="button"
              onClick={() => setRawSearch('')}
              style={{ cursor: 'pointer' }}
            />
          ) : null
        }
        style={{ flex: 1, minWidth: 200 }}
      />
      <TagsFilterBar
        selectedIds={tagFilter.selectedIds}
        match={tagFilter.match}
        onChange={handleTagFilterChange}
      />
      <Button
        variant="default"
        leftSection={<IconSettings size={14} />}
        onClick={() => setManagerOpen(true)}
      >
        {t('tags.filter.manage_tags')}
      </Button>
      <Tooltip label={t('categories.filters.fresh_tooltip')}>
        <Switch
          label={t('categories.filters.fresh_label')}
          checked={fresh}
          onChange={(e) => setFresh(e.currentTarget.checked)}
        />
      </Tooltip>
    </Group>
  );

  const modal = (
    <TagsManagerModal opened={managerOpen} onClose={() => setManagerOpen(false)} />
  );

  if (!isLoading && items.length === 0) {
    if (debounced) {
      return (
        <Stack gap="md">
          {filterRow}
          <EmptyState
            title={t('categories.empty_state.no_search_results_title', { term: debounced })}
            body={
              <Button variant="default" onClick={() => setRawSearch('')}>
                {t('categories.empty_state.clear_search')}
              </Button>
            }
          />
          {modal}
        </Stack>
      );
    }
    if (fresh) {
      return (
        <Stack gap="md">
          {filterRow}
          <EmptyState
            title={t('categories.empty_state.no_fresh_tracks_title')}
            body={
              <Button variant="default" onClick={() => setFresh(false)}>
                {t('categories.empty_state.disable_fresh')}
              </Button>
            }
          />
          {modal}
        </Stack>
      );
    }
    return (
      <Stack gap="md">
        {filterRow}
        <EmptyState
          title={t('categories.empty_state.no_tracks_title')}
          body={t('categories.empty_state.no_tracks_body')}
        />
        {modal}
      </Stack>
    );
  }

  if (isMobile) {
    return (
      <Stack gap="md">
        {filterRow}
        {items.map((tr) => (
          <TrackRow
            key={tr.id}
            track={tr}
            variant="mobile"
            categoryId={categoryId}
            actions={
              <TrackRowActions
                track={tr}
                currentCategoryId={categoryId}
                styleId={styleId}
              />
            }
          />
        ))}
        {hasNextPage && (
          <Button onClick={() => fetchNextPage()} loading={isFetchingNextPage} variant="default">
            {t('categories.detail.tracks_load_more', { remaining })}
          </Button>
        )}
        {modal}
      </Stack>
    );
  }

  return (
    <Stack gap="md">
      {filterRow}
      <Table>
        <Table.Thead>
          <Table.Tr>
            <SortableTh
              active={sortKey === 'title'}
              dir={sortDir}
              onClick={() => handleSort('title')}
            >
              {t('categories.tracks_table.title')}
            </SortableTh>
            <Table.Th>{t('categories.tracks_table.tags')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.artists')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.label')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.bpm')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.length')}</Table.Th>
            <SortableTh
              active={sortKey === 'spotify_release_date'}
              dir={sortDir}
              onClick={() => handleSort('spotify_release_date')}
            >
              {t('categories.tracks_table.released')}
            </SortableTh>
            <SortableTh
              active={sortKey === 'added_at'}
              dir={sortDir}
              onClick={() => handleSort('added_at')}
            >
              {t('categories.tracks_table.added')}
            </SortableTh>
            <Table.Th aria-hidden style={{ width: 40 }} />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.map((track) => (
            <TrackRow
              key={track.id}
              track={track}
              variant="desktop"
              categoryId={categoryId}
              actions={
                <TrackRowActions
                  track={track}
                  currentCategoryId={categoryId}
                  styleId={styleId}
                />
              }
            />
          ))}
        </Table.Tbody>
      </Table>
      {hasNextPage && (
        <Group justify="center">
          <Button onClick={() => fetchNextPage()} loading={isFetchingNextPage} variant="default">
            {t('categories.detail.tracks_load_more', { remaining })}
          </Button>
        </Group>
      )}
      {modal}
    </Stack>
  );
}
