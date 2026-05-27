import { Stack, Tabs, SimpleGrid, Card, Text } from '@mantine/core';
import { useParams, Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useArtistEnrichmentRunDetail } from '../hooks/useArtistEnrichmentRunDetail';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { ArtistRunDetailHeader } from '../components/enrichment/ArtistRunDetailHeader';
import { ArtistRunDetailCellsTable } from '../components/enrichment/ArtistRunDetailCellsTable';
import { RunJsonViewer } from '../components/enrichment/RunJsonViewer';

export function AdminArtistEnrichmentRunDetailPage() {
  const { t } = useTranslation();
  const { runId } = useParams<{ runId: string }>();
  const query = useArtistEnrichmentRunDetail(runId ?? null);
  if (!runId) return <Navigate to="/admin/artists/enrich/runs" replace />;

  if (query.isLoading) return <FullScreenLoader />;
  if (query.isError || !query.data) return <Text c="red">Run not found</Text>;

  const run = query.data;
  const cells = run.cells ?? [];

  return (
    <Stack gap="md">
      <ArtistRunDetailHeader run={run} />
      <Tabs defaultValue="summary">
        <Tabs.List>
          <Tabs.Tab value="summary">{t('admin_enrichment.run_detail.tab_summary')}</Tabs.Tab>
          <Tabs.Tab value="cells">{t('admin_enrichment.run_detail.tab_cells')}</Tabs.Tab>
          <Tabs.Tab value="json">{t('admin_enrichment.run_detail.tab_json')}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="summary" pt="md">
          <SimpleGrid cols={3}>
            <Card withBorder><Text size="sm">{t('admin_enrichment.run_detail.counters_total')}</Text><Text fw={700}>{run.cells_total}</Text></Card>
            <Card withBorder><Text size="sm">{t('admin_enrichment.run_detail.counters_ok')}</Text><Text fw={700}>{run.cells_ok}</Text></Card>
            <Card withBorder><Text size="sm">{t('admin_enrichment.run_detail.counters_err')}</Text><Text fw={700}>{run.cells_error}</Text></Card>
          </SimpleGrid>
        </Tabs.Panel>
        <Tabs.Panel value="cells" pt="md">
          <ArtistRunDetailCellsTable cells={cells} />
        </Tabs.Panel>
        <Tabs.Panel value="json" pt="md">
          <RunJsonViewer data={run} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
