import { Stack, Title, Button, Center, Text } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLabelBacklog } from '../hooks/useLabelBacklog';
import { BacklogToolbar } from '../components/enrichment/BacklogToolbar';
import { BacklogTable } from '../components/enrichment/BacklogTable';
import { EnqueueDrawer } from '../components/enrichment/EnqueueDrawer';

export function AdminEnrichmentBacklogPage() {
  const { t } = useTranslation();
  const [style, setStyle] = useState<string>('');
  const [status, setStatus] = useState<'all' | 'none' | 'failed' | 'outdated'>('all');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [drawerOpen, setDrawerOpen] = useState(false);

  const query = useLabelBacklog({ style, status });
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];

  const toggleAll = (next: boolean) =>
    setSelected((cur) => {
      const copy = new Set(cur);
      for (const i of items) {
        if (next) copy.add(i.id);
        else copy.delete(i.id);
      }
      return copy;
    });
  const toggle = (id: string) =>
    setSelected((cur) => {
      const copy = new Set(cur);
      if (copy.has(id)) copy.delete(id);
      else copy.add(id);
      return copy;
    });

  return (
    <Stack gap="md">
      <Title order={3}>{t('admin_enrichment.backlog.title')}</Title>
      <BacklogToolbar
        style={style}
        onStyleChange={setStyle}
        status={status}
        onStatusChange={setStatus}
        selectedCount={selected.size}
        onEnqueueClick={() => setDrawerOpen(true)}
      />
      {items.length === 0 && !query.isLoading ? (
        <Center mt="lg"><Text c="dimmed">{t('admin_enrichment.backlog.empty')}</Text></Center>
      ) : (
        <BacklogTable items={items} selected={selected} onToggle={toggle} onToggleAll={toggleAll} />
      )}
      {query.hasNextPage && (
        <Center mt="md">
          <Button variant="default" loading={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
            Load more
          </Button>
        </Center>
      )}
      <EnqueueDrawer
        opened={drawerOpen}
        onClose={() => { setDrawerOpen(false); setSelected(new Set()); }}
        labelIds={Array.from(selected)}
      />
    </Stack>
  );
}
