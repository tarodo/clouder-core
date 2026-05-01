import { useState } from 'react';
import { Button, Group, Stack, Table, TextInput } from '@mantine/core';
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks';
import { IconSearch, IconX } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useCategoryTracks } from '../hooks/useCategoryTracks';
import { TrackRow } from './TrackRow';
import { EmptyState } from '../../../components/EmptyState';

export interface TracksTabProps {
  categoryId: string;
}

export function TracksTab({ categoryId }: TracksTabProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const [rawSearch, setRawSearch] = useState('');
  const [debounced] = useDebouncedValue(rawSearch.trim().toLowerCase(), 300);

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } = useCategoryTracks(
    categoryId,
    debounced,
  );

  const items = data?.pages.flatMap((p) => p.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;
  const remaining = Math.max(0, total - items.length);

  const searchInput = (
    <TextInput
      placeholder={t('categories.detail.tracks_search_placeholder')}
      leftSection={<IconSearch size={16} />}
      value={rawSearch}
      onChange={(e) => setRawSearch(e.currentTarget.value)}
      rightSection={
        rawSearch ? (
          <IconX size={16} role="button" onClick={() => setRawSearch('')} style={{ cursor: 'pointer' }} />
        ) : null
      }
    />
  );

  if (!isLoading && items.length === 0) {
    if (debounced) {
      return (
        <Stack gap="md">
          {searchInput}
          <EmptyState
            title={t('categories.empty_state.no_search_results_title', { term: debounced })}
            body={
              <Button variant="default" onClick={() => setRawSearch('')}>
                {t('categories.empty_state.clear_search')}
              </Button>
            }
          />
        </Stack>
      );
    }
    return (
      <Stack gap="md">
        {searchInput}
        <EmptyState
          title={t('categories.empty_state.no_tracks_title')}
          body={t('categories.empty_state.no_tracks_body')}
        />
      </Stack>
    );
  }

  if (isMobile) {
    return (
      <Stack gap="md">
        {searchInput}
        {items.map((tr) => (
          <TrackRow key={tr.id} track={tr} variant="mobile" />
        ))}
        {hasNextPage && (
          <Button onClick={() => fetchNextPage()} loading={isFetchingNextPage} variant="default">
            {t('categories.detail.tracks_load_more', { remaining })}
          </Button>
        )}
      </Stack>
    );
  }

  return (
    <Stack gap="md">
      {searchInput}
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('categories.tracks_table.title')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.artists')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.bpm')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.length')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.added')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.map((track) => (
            <TrackRow key={track.id} track={track} variant="desktop" />
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
    </Stack>
  );
}
