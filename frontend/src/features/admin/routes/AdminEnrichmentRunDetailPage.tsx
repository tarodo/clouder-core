import { Stack, Tabs, SimpleGrid, Card, Text } from '@mantine/core';
import { useParams, Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useEnrichmentRunDetail } from '../hooks/useEnrichmentRunDetail';
import { Ghost, GhostScope } from '../../../components/Ghost';
import type { RunDetail } from '../../../api/labels';
import { EmptyState } from '../../../components/EmptyState';
import { RunDetailHeader } from '../components/enrichment/RunDetailHeader';
import { RunDetailCellsTable } from '../components/enrichment/RunDetailCellsTable';
import { RunJsonViewer } from '../components/enrichment/RunJsonViewer';

const RUN_GHOST: RunDetail = {
  id: 'ghost000-0000-0000-0000-000000000000',
  status: 'completed',
  source: 'manual',
  created_at: '2026-01-01T00:00:00Z',
  cells_total: 3,
  cells_ok: 3,
  cells_error: 0,
  cost_usd: 0.0042,
  prompt_slug: 'placeholder',
  prompt_version: 'v1',
  vendors: ['placeholder'],
  cells: [],
};

export function AdminEnrichmentRunDetailPage() {
  const { t } = useTranslation();
  const { runId } = useParams<{ runId: string }>();
  const query = useEnrichmentRunDetail(runId ?? null);
  if (!runId) return <Navigate to="/admin/labels/enrich/runs" replace />;

  // Loading: the page itself as a ghost of a typical run.
  const run = query.data ?? (query.isLoading ? RUN_GHOST : undefined);
  if (!run) return <EmptyState variant="page" title={t('admin_enrichment.run_detail.not_found')} />;
  const cells = run.cells ?? [];

  const page = (
    <Stack gap="md">
      <RunDetailHeader run={run} />
      <Tabs defaultValue="summary">
        <Tabs.List>
          <Tabs.Tab value="summary">{t('admin_enrichment.run_detail.tab_summary')}</Tabs.Tab>
          <Tabs.Tab value="cells">{t('admin_enrichment.run_detail.tab_cells')}</Tabs.Tab>
          <Tabs.Tab value="json">{t('admin_enrichment.run_detail.tab_json')}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="summary" pt="md">
          <SimpleGrid cols={3}>
            <Card withBorder><Text size="sm">{t('admin_enrichment.run_detail.counters_total')}</Text><Ghost><Text fw={700}>{run.cells_total}</Text></Ghost></Card>
            <Card withBorder><Text size="sm">{t('admin_enrichment.run_detail.counters_ok')}</Text><Ghost><Text fw={700}>{run.cells_ok}</Text></Ghost></Card>
            <Card withBorder><Text size="sm">{t('admin_enrichment.run_detail.counters_err')}</Text><Ghost><Text fw={700}>{run.cells_error}</Text></Ghost></Card>
          </SimpleGrid>
        </Tabs.Panel>
        <Tabs.Panel value="cells" pt="md">
          <RunDetailCellsTable cells={cells} />
        </Tabs.Panel>
        <Tabs.Panel value="json" pt="md">
          <RunJsonViewer data={run} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
  return <GhostScope on={!query.data}>{page}</GhostScope>;
}
