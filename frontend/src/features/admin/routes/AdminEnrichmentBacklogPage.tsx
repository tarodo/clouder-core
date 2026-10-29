import { Stack, Button, Center } from '@mantine/core';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLabelBacklog, type LabelStatusFilter } from '../hooks/useLabelBacklog';
import { BacklogToolbar, type StyleFilterOption } from '../components/enrichment/BacklogToolbar';
import { BacklogTable, ghostBacklog } from '../components/enrichment/BacklogTable';
import { Ghost, GhostScope, useRemembered } from '../../../components/Ghost';
import { EnqueueDrawer } from '../components/enrichment/EnqueueDrawer';
import { LabelHistoryDrawer } from '../components/enrichment/LabelHistoryDrawer';
import { useAllStyles } from '../../../hooks/useAllStyles';
import { slugifyStyle } from '../../library/lib/slugifyStyle';
import { PageHeader } from '../../../components/PageHeader';
import { EmptyState } from '../../../components/EmptyState';

export function AdminEnrichmentBacklogPage() {
  const { t } = useTranslation();
  const [style, setStyle] = useState<string>('');
  const [status, setStatus] = useState<LabelStatusFilter>('all');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [historyFor, setHistoryFor] = useState<{ id: string; name: string } | null>(null);

  const stylesQuery = useAllStyles();
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
  const loaded = query.data?.pages.flatMap((p) => p.items);
  // While the first page loads: the table's ghost, as long as it was last time.
  const rows = useRemembered('admin.labels.backlog', loaded?.length, 10);
  const more = useRemembered('admin.labels.backlog.more', loaded && Number(!!query.hasNextPage), 0);
  const items = loaded ?? [];
  const shown = query.isLoading ? ghostBacklog(rows) : items;

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
      <PageHeader
        title={t('admin_enrichment.backlog.title')}
        subtitle={t('admin_enrichment.backlog.subtitle')}
      >
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
      </PageHeader>
      <GhostScope on={query.isLoading}>
        {shown.length === 0 ? (
          <Ghost block>
            <EmptyState variant="inline" title={t('admin_enrichment.backlog.empty')} />
          </Ghost>
        ) : (
          <BacklogTable
            items={shown}
            selected={selected}
            onToggle={toggle}
            onToggleAll={toggleAll}
            styleNames={styleNames}
            onShowHistory={(row) => setHistoryFor({ id: row.id, name: row.name })}
          />
        )}
        {(query.isLoading ? more > 0 : query.hasNextPage) && (
          <Center mt="md">
            <Ghost>
              <Button
                variant="default"
                loading={query.isFetchingNextPage}
                onClick={() => query.fetchNextPage()}
              >
                {t('admin_enrichment.backlog.load_more')}
              </Button>
            </Ghost>
          </Center>
        )}
      </GhostScope>
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
