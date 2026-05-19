import { Stack, Title, Button, Center, Text } from '@mantine/core';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLabelBacklog, type LabelStatusFilter } from '../hooks/useLabelBacklog';
import { BacklogToolbar, type StyleFilterOption } from '../components/enrichment/BacklogToolbar';
import { BacklogTable } from '../components/enrichment/BacklogTable';
import { EnqueueDrawer } from '../components/enrichment/EnqueueDrawer';
import { LabelHistoryDrawer } from '../components/enrichment/LabelHistoryDrawer';
import { useStyles } from '../../../hooks/useStyles';
import { slugifyStyle } from '../../library/lib/slugifyStyle';

export function AdminEnrichmentBacklogPage() {
  const { t } = useTranslation();
  const [style, setStyle] = useState<string>('');
  const [status, setStatus] = useState<LabelStatusFilter>('all');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [historyFor, setHistoryFor] = useState<{ id: string; name: string } | null>(null);

  const stylesQuery = useStyles();
  const styleOptions: ReadonlyArray<StyleFilterOption> = useMemo(
    () =>
      stylesQuery.data?.items.map((s) => ({
        value: slugifyStyle(s.name),
        label: s.name,
      })) ?? [],
    [stylesQuery.data],
  );
  const styleNames: Record<string, string> = useMemo(() => {
    const map: Record<string, string> = {};
    for (const s of stylesQuery.data?.items ?? []) {
      map[slugifyStyle(s.name)] = s.name;
    }
    return map;
  }, [stylesQuery.data]);

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
        styleOptions={styleOptions}
        stylesLoading={stylesQuery.isLoading}
      />
      {items.length === 0 && !query.isLoading ? (
        <Center mt="lg">
          <Text c="dimmed">{t('admin_enrichment.backlog.empty')}</Text>
        </Center>
      ) : (
        <BacklogTable
          items={items}
          selected={selected}
          onToggle={toggle}
          onToggleAll={toggleAll}
          styleNames={styleNames}
          onShowHistory={(row) => setHistoryFor({ id: row.id, name: row.name })}
        />
      )}
      {query.hasNextPage && (
        <Center mt="md">
          <Button
            variant="default"
            loading={query.isFetchingNextPage}
            onClick={() => query.fetchNextPage()}
          >
            {t('admin_enrichment.backlog.load_more')}
          </Button>
        </Center>
      )}
      <EnqueueDrawer
        opened={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
          setSelected(new Set());
        }}
        labelIds={Array.from(selected)}
      />
      <LabelHistoryDrawer
        opened={historyFor !== null}
        onClose={() => setHistoryFor(null)}
        labelId={historyFor?.id ?? null}
        labelName={historyFor?.name}
      />
    </Stack>
  );
}
