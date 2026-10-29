import { Button, Group, Pagination, Stack, Table, Text, TextInput } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useDebouncedValue } from '@mantine/hooks';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../../api/client';
import { Ghost, GhostScope, GhostTd, useRemembered } from '../../../components/Ghost';
import { useRetrySpotifySearch } from '../hooks/useRetrySpotifySearch';
import { useSpotifyNotFound } from '../hooks/useSpotifyNotFound';

const LIMIT = 50;

export function SpotifyNotFoundTable() {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [debouncedSearch] = useDebouncedValue(search, 300);
  const [page, setPage] = useState(1);
  const [dates, setDates] = useState<[string | null, string | null]>([null, null]);
  const [confirming, setConfirming] = useState(false);
  const offset = (page - 1) * LIMIT;
  const q = useSpotifyNotFound({
    limit: LIMIT,
    offset,
    search: debouncedSearch,
    publishDateFrom: dates[0],
    publishDateTo: dates[1],
  });
  const retry = useRetrySpotifySearch();
  const rows = useRemembered('admin.spotify_not_found.rows', q.data?.items.length, 10);
  const pages = useRemembered(
    'admin.spotify_not_found.pages',
    q.data && Math.max(1, Math.ceil(q.data.total / LIMIT)),
    1,
  );

  const canRetry = Boolean(dates[0] && dates[1]);

  async function confirmRetry() {
    if (confirming) return;
    setConfirming(true);
    let total: number;
    try {
      const params = new URLSearchParams({ limit: '1', offset: '0' });
      params.set('publish_date_from', dates[0]!);
      params.set('publish_date_to', dates[1]!);
      const res = await api<{ total: number }>(
        `/tracks/spotify-not-found?${params.toString()}`,
      );
      total = res.total;
    } catch {
      notifications.show({
        color: 'red',
        message: t('admin.spotify_not_found.retry_failed'),
      });
      return;
    } finally {
      setConfirming(false);
    }

    modals.openConfirmModal({
      title: t('admin.spotify_not_found.retry_title'),
      children: (
        <Text size="sm">
          {t('admin.spotify_not_found.retry_confirm', { count: total })}
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

  if (q.isError) return <Text c="red">{t('admin.spotify_not_found.load_failed')}</Text>;
  // Loading: the filters stay live, the list below them is a ghost as long as last time.
  const ghost = q.isLoading;
  const data = q.data ?? {
    total: pages * LIMIT,
    items: Array.from({ length: rows }, (_, i) => ({
      track_id: `ghost-${i}`,
      title: 'Placeholder title',
      artists: ['Placeholder artist'],
      isrc: 'GBXXX0000000',
    })),
  };

  const totalPages = Math.max(1, Math.ceil(data.total / LIMIT));

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
        <Button
          onClick={confirmRetry}
          disabled={!canRetry}
          loading={retry.isPending || confirming}
        >
          {t('admin.spotify_not_found.retry_button')}
        </Button>
      </Group>
      <GhostScope on={ghost}>
        <Ghost>
          <Text size="sm" c="dimmed">
            {t('admin.spotify_not_found.total_label', { count: data.total })}
          </Text>
        </Ghost>
        <Table striped withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Title</Table.Th>
              <Table.Th>Artists</Table.Th>
              <Table.Th>ISRC</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data.items.map((t) => (
              <Table.Tr key={t.track_id}>
                <GhostTd>{t.title}</GhostTd>
                <GhostTd>{t.artists.join(', ')}</GhostTd>
                <GhostTd>{t.isrc ?? '—'}</GhostTd>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Ghost>
          <Pagination value={page} onChange={setPage} total={totalPages} />
        </Ghost>
      </GhostScope>
    </Stack>
  );
}
