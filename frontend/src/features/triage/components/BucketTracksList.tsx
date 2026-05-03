import { useState } from 'react';
import { Button, Group, Stack, Table, TextInput } from '@mantine/core';
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { IconSearch, IconX } from '../../../components/icons';
import { EmptyState } from '../../../components/EmptyState';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { useBucketTracks } from '../hooks/useBucketTracks';
import { BucketTrackRow } from './BucketTrackRow';
import type { TriageBucket } from '../lib/bucketLabels';

export interface BucketTracksListProps {
  blockId: string;
  bucket: TriageBucket;
  buckets: TriageBucket[];
  showMoveMenu: boolean;
  onMove: (trackId: string, toBucket: TriageBucket) => void;
}

export function BucketTracksList({
  blockId,
  bucket,
  buckets,
  showMoveMenu,
  onMove,
}: BucketTracksListProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const [rawSearch, setRawSearch] = useState('');
  const [debounced] = useDebouncedValue(rawSearch.trim(), 300);
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } = useBucketTracks(
    blockId,
    bucket.id,
    debounced,
  );

  const items = data?.pages.flatMap((p) => p.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;
  const remaining = Math.max(0, total - items.length);

  const searchInput = (
    <TextInput
      placeholder={t('triage.bucket.search_placeholder')}
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
            aria-label={t('triage.bucket.empty.search_miss_clear')}
          />
        ) : null
      }
    />
  );

  if (isLoading) {
    return (
      <Stack gap="md">
        {searchInput}
        <FullScreenLoader />
      </Stack>
    );
  }

  if (items.length === 0) {
    if (debounced) {
      return (
        <Stack gap="md">
          {searchInput}
          <EmptyState
            title={t('triage.bucket.empty.search_miss_title')}
            body={
              <Button variant="default" onClick={() => setRawSearch('')}>
                {t('triage.bucket.empty.search_miss_clear')}
              </Button>
            }
          />
        </Stack>
      );
    }
    const bodyKey =
      bucket.bucket_type === 'UNCLASSIFIED'
        ? 'triage.bucket.empty.no_tracks_body_unclassified'
        : 'triage.bucket.empty.no_tracks_body_default';
    return (
      <Stack gap="md">
        {searchInput}
        <EmptyState
          title={t('triage.bucket.empty.no_tracks_title')}
          body={t(bodyKey)}
        />
      </Stack>
    );
  }

  const rows = items.map((tr) => (
    <BucketTrackRow
      key={tr.track_id}
      track={tr}
      variant={isMobile ? 'mobile' : 'desktop'}
      buckets={buckets}
      currentBucketId={bucket.id}
      onMove={(b) => onMove(tr.track_id, b)}
      showMoveMenu={showMoveMenu}
    />
  ));

  if (isMobile) {
    return (
      <Stack gap="md">
        {searchInput}
        {rows}
        {hasNextPage && (
          <Button
            onClick={() => fetchNextPage()}
            loading={isFetchingNextPage}
            variant="default"
          >
            {t('triage.bucket.load_more')}
            {remaining > 0 ? ` (${remaining})` : ''}
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
            <Table.Th>{t('triage.tracks_table.title_header')}</Table.Th>
            <Table.Th>{t('triage.tracks_table.artists_header')}</Table.Th>
            <Table.Th>{t('triage.tracks_table.bpm_header')}</Table.Th>
            <Table.Th>{t('triage.tracks_table.length_header')}</Table.Th>
            <Table.Th>{t('triage.tracks_table.released_header')}</Table.Th>
            <Table.Th aria-label={t('triage.tracks_table.actions_header')} />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>{rows}</Table.Tbody>
      </Table>
      {hasNextPage && (
        <Group justify="center">
          <Button
            onClick={() => fetchNextPage()}
            loading={isFetchingNextPage}
            variant="default"
          >
            {t('triage.bucket.load_more')}
            {remaining > 0 ? ` (${remaining})` : ''}
          </Button>
        </Group>
      )}
    </Stack>
  );
}
