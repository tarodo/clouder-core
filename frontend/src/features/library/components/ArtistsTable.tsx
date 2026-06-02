import {
  Table,
  Anchor,
  Group,
  Text,
  Center,
  Pagination,
  Skeleton,
} from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { ArtistSummary } from '../../../api/artists';
import { countryFlag } from '../lib/countryFlag';
import { truncateTagline } from '../lib/formatLabel';
import { ArtistPreferenceButtons } from './ArtistPreferenceButtons';

interface Props {
  items: ArtistSummary[];
  isLoading: boolean;
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
}

export function ArtistsTable(p: Props) {
  const { t } = useTranslation();

  if (p.isLoading && p.items.length === 0) {
    return <Skeleton height={320} />;
  }

  if (p.items.length === 0) {
    return (
      <Center mt="lg">
        <Text c="dimmed">{t('library.list.empty_filter')}</Text>
      </Center>
    );
  }

  return (
    <>
      <Table verticalSpacing="sm" highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('library.list.col_name')}</Table.Th>
            <Table.Th>{t('library.list.col_country')}</Table.Th>
            <Table.Th>{t('library.artists_list.col_active_since')}</Table.Th>
            <Table.Th>{t('library.list.col_tracks')}</Table.Th>
            <Table.Th>{t('library.list.col_ai_detected')}</Table.Th>
            <Table.Th>{t('library.artists_list.col_preference')}</Table.Th>
            <Table.Th>{t('library.list.col_description')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {p.items.map((it) => {
            const info = it.info ?? null;
            const aiContent = info?.ai_content ? info.ai_content.toUpperCase() : null;
            return (
              <Table.Tr key={it.id}>
                <Table.Td>
                  <Anchor component={Link} to={`/artists/${it.id}`} fw={500}>
                    {it.name}
                  </Anchor>
                </Table.Td>
                <Table.Td>
                  {info?.country ? (
                    <Group gap={4} wrap="nowrap">
                      <Text>{countryFlag(info.country)}</Text>
                      <Text size="sm">{info.country}</Text>
                    </Group>
                  ) : (
                    <Text size="sm" c="dimmed">
                      —
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  {info?.active_since ? (
                    <Text size="sm">{info.active_since}</Text>
                  ) : (
                    <Text size="sm" c="dimmed">
                      —
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{it.track_count}</Text>
                </Table.Td>
                <Table.Td>
                  {aiContent ? (
                    <Text size="sm">{aiContent}</Text>
                  ) : (
                    <Text size="sm" c="dimmed">
                      —
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <ArtistPreferenceButtons
                    artistId={it.id}
                    current={it.my_preference ?? null}
                    size="sm"
                  />
                </Table.Td>
                <Table.Td>
                  <Text size="sm" lineClamp={2} maw={420}>
                    {info?.tagline ? truncateTagline(info.tagline, 220) : '—'}
                  </Text>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
      {p.pageCount > 1 && (
        <Center mt="md">
          <Pagination
            total={p.pageCount}
            value={p.page}
            onChange={p.onPageChange}
            withEdges
          />
        </Center>
      )}
    </>
  );
}
