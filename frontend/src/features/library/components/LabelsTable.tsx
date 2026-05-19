import {
  Table,
  Anchor,
  Badge,
  Group,
  Text,
  Center,
  Button,
  Skeleton,
} from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useEffect, useRef } from 'react';
import type { LabelSummary } from '../../../api/labels';
import { countryFlag } from '../lib/countryFlag';
import { truncateTagline } from '../lib/formatLabel';

interface Props {
  items: LabelSummary[];
  styleId: string;
  /** Slug -> display name map for the Style column. */
  styleNames?: Readonly<Record<string, string>>;
  isLoading: boolean;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onLoadMore: () => void;
}

export function LabelsTable(p: Props) {
  const { t } = useTranslation();
  const sentinel = useRef<HTMLTableRowElement | null>(null);

  useEffect(() => {
    if (!p.hasNextPage) return;
    const el = sentinel.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => entries[0]?.isIntersecting && p.onLoadMore(),
      { rootMargin: '200px' },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [p.hasNextPage, p.onLoadMore]);

  if (p.isLoading) {
    return (
      <Skeleton height={320} />
    );
  }

  if (p.items.length === 0) {
    return (
      <Center mt="lg">
        <Text c="dimmed">{t('library.list.empty_filter')}</Text>
      </Center>
    );
  }

  const displayStyle = (slug: string) =>
    (p.styleNames && p.styleNames[slug]) || slug || '—';

  return (
    <>
      <Table verticalSpacing="sm" highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('library.list.col_name')}</Table.Th>
            <Table.Th>{t('library.list.col_style')}</Table.Th>
            <Table.Th>{t('library.list.col_country')}</Table.Th>
            <Table.Th>{t('library.list.col_founded')}</Table.Th>
            <Table.Th>{t('library.list.col_description')}</Table.Th>
            <Table.Th>{t('library.list.col_status')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {p.items.map((it) => {
            const info = it.info ?? null;
            const hasInfo = it.status === 'completed' && info != null;
            return (
              <Table.Tr key={it.id}>
                <Table.Td>
                  <Anchor component={Link} to={`/library/${p.styleId}/labels/${it.id}`} fw={500}>
                    {it.name}
                  </Anchor>
                </Table.Td>
                <Table.Td>{displayStyle(it.style)}</Table.Td>
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
                  {info?.founded_year ? (
                    <Text size="sm">{info.founded_year}</Text>
                  ) : (
                    <Text size="sm" c="dimmed">
                      —
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Text size="sm" lineClamp={2} maw={420}>
                    {info?.tagline ? truncateTagline(info.tagline, 220) : '—'}
                  </Text>
                </Table.Td>
                <Table.Td>
                  {hasInfo ? (
                    <Badge color="green" variant="light">
                      {t('library.list.status_has_info')}
                    </Badge>
                  ) : (
                    <Badge color="gray" variant="light">
                      {t('library.list.status_pending')}
                    </Badge>
                  )}
                </Table.Td>
              </Table.Tr>
            );
          })}
          {p.hasNextPage && (
            <Table.Tr ref={sentinel}>
              <Table.Td colSpan={6} />
            </Table.Tr>
          )}
        </Table.Tbody>
      </Table>
      {p.hasNextPage && (
        <Center mt="md">
          <Button
            onClick={p.onLoadMore}
            loading={p.isFetchingNextPage}
            variant="default"
          >
            {t('library.list.load_more')}
          </Button>
        </Center>
      )}
    </>
  );
}
