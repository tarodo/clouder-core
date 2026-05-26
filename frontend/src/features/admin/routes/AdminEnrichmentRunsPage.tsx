import { Stack, Title, Select, Button, Center, Group, SegmentedControl, Text } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useEnrichmentRuns } from '../hooks/useEnrichmentRuns';
import { RunsTable } from '../components/enrichment/RunsTable';

export function AdminEnrichmentRunsPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<'all' | 'queued' | 'running' | 'completed' | 'failed'>('all');
  const [source, setSource] = useState<'all' | 'manual' | 'auto'>('all');
  const query = useEnrichmentRuns({
    status,
    source: source === 'all' ? undefined : source,
  });
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <Stack gap="md">
      <Title order={3}>{t('admin_enrichment.runs.title')}</Title>
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
      <RunsTable items={items} />
      {query.hasNextPage && (
        <Center mt="md">
          <Button variant="default" loading={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
            Load more
          </Button>
        </Center>
      )}
    </Stack>
  );
}
