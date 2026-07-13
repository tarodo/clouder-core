import { Button, Group, Pagination, Skeleton, Stack, Table, Text, TextInput } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useDebouncedValue } from '@mantine/hooks';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useRetrySpotifySearch } from '../hooks/useRetrySpotifySearch';
import { useSpotifyNotFound } from '../hooks/useSpotifyNotFound';

const LIMIT = 50;

export function SpotifyNotFoundTable() {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [debouncedSearch] = useDebouncedValue(search, 300);
  const [page, setPage] = useState(1);
  const [dates, setDates] = useState<[string | null, string | null]>([null, null]);
  const offset = (page - 1) * LIMIT;
  const q = useSpotifyNotFound({
    limit: LIMIT,
    offset,
    search: debouncedSearch,
    publishDateFrom: dates[0],
    publishDateTo: dates[1],
  });
  const retry = useRetrySpotifySearch();

  const canRetry = Boolean(dates[0] && dates[1]);

  function confirmRetry() {
    modals.openConfirmModal({
      title: t('admin.spotify_not_found.retry_title'),
      children: (
        <Text size="sm">
          {t('admin.spotify_not_found.retry_confirm', { count: q.data?.total ?? 0 })}
        </Text>
      ),
      labels: {
        confirm: t('admin.spotify_not_found.retry_confirm_label'),
        cancel: t('admin.spotify_not_found.retry_cancel_label'),
      },
      onConfirm: () =>
        retry.mutate(
          { publish_date_from: dates[0]!, publish_date_to: dates[1]! },
          {
            onSuccess: (data) => {
              notifications.show({
                message:
                  data.queued_count > 0
                    ? t('admin.spotify_not_found.retry_queued', {
                        count: data.queued_count,
                      })
                    : t('admin.spotify_not_found.retry_nothing'),
              });
            },
            onError: () => {
              notifications.show({
                color: 'red',
                message: t('admin.spotify_not_found.retry_failed'),
              });
            },
          },
        ),
    });
  }

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
      <Group align="end">
        <DatePickerInput
          type="range"
          allowSingleDateInRange
          clearable
          label={t('admin.spotify_not_found.date_range')}
          value={dates}
          onChange={(value) => {
            setDates(value);
            setPage(1);
          }}
        />
        <Button onClick={confirmRetry} disabled={!canRetry} loading={retry.isPending}>
          {t('admin.spotify_not_found.retry_button')}
        </Button>
      </Group>
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
