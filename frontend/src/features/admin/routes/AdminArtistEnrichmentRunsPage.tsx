import { Stack, Select, Center, Group, SegmentedControl, Text, Alert, Button } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useArtistEnrichmentRuns } from '../hooks/useArtistEnrichmentRuns';
import { ArtistRunsTable, ghostRuns } from '../components/enrichment/ArtistRunsTable';
import { Ghost, GhostScope, useRemembered } from '../../../components/Ghost';
import { PageHeader } from '../../../components/PageHeader';
import { EmptyState } from '../../../components/EmptyState';

export function AdminArtistEnrichmentRunsPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<'all' | 'queued' | 'running' | 'completed' | 'failed'>('all');
  const [source, setSource] = useState<'all' | 'manual' | 'auto'>('all');
  const query = useArtistEnrichmentRuns({
    status,
    source: source === 'all' ? undefined : source,
  });
  const loaded = query.data?.pages.flatMap((p) => p.items);
  // While the first page loads: the table's ghost, as long as it was last time.
  const rows = useRemembered('admin.artists.runs', loaded?.length, 10);
  const more = useRemembered('admin.artists.runs.more', loaded && Number(!!query.hasNextPage), 0);
  const items = query.isLoading ? ghostRuns(rows) : (loaded ?? []);

  return (
    <Stack gap="md">
      <PageHeader title={t('admin_enrichment.runs.title')} subtitle={t('admin_enrichment.runs.subtitle')}>
        <Group align="flex-end">
          <Select
            label={t('admin_enrichment.runs.filter_status')}
            value={status}
            onChange={(v) => v && setStatus(v as typeof status)}
            data={[
              { value: 'all', label: 'all' },
              { value: 'queued', label: t('admin_enrichment.status.queued') },
              { value: 'running', label: t('admin_enrichment.status.running') },
              { value: 'completed', label: t('admin_enrichment.status.completed') },
              { value: 'failed', label: t('admin_enrichment.status.failed') },
            ]}
            maw={240}
          />
          <Stack gap={4}>
            <Text size="sm" fw={500}>{t('admin_enrichment.runs.filter_source')}</Text>
            <SegmentedControl
              value={source}
              onChange={(v) => setSource(v as typeof source)}
              data={[
                { value: 'all', label: t('admin_enrichment.runs.source_all') },
                { value: 'manual', label: t('admin_enrichment.runs.source_manual') },
                { value: 'auto', label: t('admin_enrichment.runs.source_auto') },
              ]}
            />
          </Stack>
        </Group>
      </PageHeader>

      {query.isError ? (
        <Alert color="red">{t('admin_enrichment.runs.load_failed')}</Alert>
      ) : (
        <GhostScope on={query.isLoading}>
          {items.length === 0 ? (
            <Ghost block>
              <EmptyState variant="inline" title={t('admin_enrichment.runs.empty')} />
            </Ghost>
          ) : (
            <ArtistRunsTable items={items} />
          )}
          {(query.isLoading ? more > 0 : query.hasNextPage) && (
            <Center mt="md">
              <Ghost>
                <Button variant="default" loading={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
                  {t('admin_enrichment.backlog.load_more')}
                </Button>
              </Ghost>
            </Center>
          )}
        </GhostScope>
      )}
    </Stack>
  );
}
