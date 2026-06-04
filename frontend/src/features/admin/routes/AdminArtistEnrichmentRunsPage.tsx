import { Stack, Select, Center, Group, SegmentedControl, Text, Alert, Button, Skeleton } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useArtistEnrichmentRuns } from '../hooks/useArtistEnrichmentRuns';
import { ArtistRunsTable } from '../components/enrichment/ArtistRunsTable';
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
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];

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
      ) : query.isLoading ? (
        <Skeleton height={320} radius="md" />
      ) : items.length === 0 ? (
        <EmptyState variant="inline" title={t('admin_enrichment.runs.empty')} />
      ) : (
        <ArtistRunsTable items={items} />
      )}

      {query.hasNextPage && (
        <Center mt="md">
          <Button variant="default" loading={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
            {t('admin_enrichment.backlog.load_more')}
          </Button>
        </Center>
      )}
    </Stack>
  );
}
