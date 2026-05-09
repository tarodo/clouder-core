import { Pagination, Skeleton, Stack, Table, Text, TextInput } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSpotifyNotFound } from '../hooks/useSpotifyNotFound';

const LIMIT = 50;

export function SpotifyNotFoundTable() {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [debouncedSearch] = useDebouncedValue(search, 300);
  const [page, setPage] = useState(1);
  const offset = (page - 1) * LIMIT;
  const q = useSpotifyNotFound({ limit: LIMIT, offset, search: debouncedSearch });

  if (q.isLoading) return <Skeleton h={400} />;
  if (q.isError) return <Text c="red">{t('admin.spotify_not_found.load_failed')}</Text>;
  if (!q.data) return null;

  const totalPages = Math.max(1, Math.ceil(q.data.total / LIMIT));

  return (
    <Stack>
      <TextInput
        placeholder={t('admin.spotify_not_found.search')}
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
      />
      <Text size="sm" c="dimmed">
        {t('admin.spotify_not_found.total_label', { count: q.data.total })}
      </Text>
      <Table striped withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Title</Table.Th>
            <Table.Th>Artists</Table.Th>
            <Table.Th>ISRC</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {q.data.items.map((t) => (
            <Table.Tr key={t.track_id}>
              <Table.Td>{t.title}</Table.Td>
              <Table.Td>{t.artists.join(', ')}</Table.Td>
              <Table.Td>{t.isrc ?? '—'}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Pagination value={page} onChange={setPage} total={totalPages} />
    </Stack>
  );
}
