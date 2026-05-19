import { useEffect, useRef } from 'react';
import { SimpleGrid, Button, Center, Text, Skeleton } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { LabelSummary } from '../../../api/labels';
import { LabelCard } from './LabelCard';

interface Props {
  items: LabelSummary[];
  styleId: string;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  isLoading: boolean;
  onLoadMore: () => void;
}

export function LabelListGrid(props: Props) {
  const { t } = useTranslation();
  const sentinel = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!props.hasNextPage) return;
    const el = sentinel.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => entries[0]?.isIntersecting && props.onLoadMore(),
      { rootMargin: '200px' },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [props.hasNextPage, props.onLoadMore]);

  if (props.isLoading) {
    return (
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} height={140} />)}
      </SimpleGrid>
    );
  }

  if (props.items.length === 0) {
    return <Center mt="lg"><Text c="dimmed">{t('library.list.empty_filter')}</Text></Center>;
  }

  return (
    <>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        {props.items.map((item) => (
          <LabelCard key={item.id} item={item} styleId={props.styleId} />
        ))}
      </SimpleGrid>
      <div ref={sentinel} />
      {props.hasNextPage && (
        <Center mt="md">
          <Button onClick={props.onLoadMore} loading={props.isFetchingNextPage} variant="default">
            {t('library.list.load_more')}
          </Button>
        </Center>
      )}
    </>
  );
}
