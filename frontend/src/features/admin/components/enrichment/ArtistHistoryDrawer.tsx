import {
  Drawer,
  Stack,
  Group,
  Title,
  Text,
  Badge,
  Skeleton,
  Alert,
  Accordion,
  Code,
  Tooltip,
  Anchor,
} from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../../../api/client';
import type { ArtistHistoryResponse, ArtistHistoryCell } from '../../../../api/artists';

interface Props {
  opened: boolean;
  onClose: () => void;
  artistId: string | null;
  artistName?: string;
}

interface RunGroup {
  runId: string;
  runStatus?: string;
  runCreatedAt?: string;
  promptSlug?: string;
  promptVersion?: string;
  cells: ArtistHistoryCell[];
}

function groupByRun(items: ArtistHistoryCell[]): RunGroup[] {
  const map = new Map<string, RunGroup>();
  for (const c of items) {
    const id = c.run_id;
    let g = map.get(id);
    if (!g) {
      g = {
        runId: id,
        runStatus: c.run_status,
        runCreatedAt: c.run_created_at,
        promptSlug: c.prompt_slug,
        promptVersion: c.prompt_version,
        cells: [],
      };
      map.set(id, g);
    }
    g.cells.push(c);
  }
  return Array.from(map.values());
}

const STATUS_COLOR: Record<string, string> = {
  queued: 'gray',
  running: 'blue',
  completed: 'green',
  failed: 'red',
  ok: 'green',
  error: 'red',
};

export function ArtistHistoryDrawer({ opened, onClose, artistId, artistName }: Props) {
  const { t } = useTranslation();
  const query = useQuery<ArtistHistoryResponse, Error>({
    queryKey: ['admin', 'artistHistory', artistId] as const,
    queryFn: () => api<ArtistHistoryResponse>(`/admin/artists/${artistId}/history`),
    enabled: !!artistId,
    staleTime: 30_000,
  });
  const groups = query.data ? groupByRun(query.data.items) : [];

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      title={
        <Stack gap={2}>
          <Title order={5}>{t('admin_enrichment.history.title')}</Title>
          {artistName && (
            <Text size="sm" c="dimmed">
              {artistName}
            </Text>
          )}
        </Stack>
      }
      position="right"
      size="xl"
    >
      {query.isLoading && <Skeleton height={200} />}
      {query.isError && (
        <Alert color="red">{String(query.error.message ?? 'error')}</Alert>
      )}
      {query.data && groups.length === 0 && (
        <Text c="dimmed">{t('admin_enrichment.history.empty')}</Text>
      )}
      {query.data && groups.length > 0 && (
        <Accordion
          multiple
          variant="separated"
          defaultValue={groups.map((g) => g.runId)}
        >
          {groups.map((g) => (
            <Accordion.Item key={g.runId} value={g.runId}>
              <Accordion.Control>
                <Group justify="space-between" wrap="nowrap">
                  <Group gap="xs" wrap="nowrap">
                    <Anchor
                      component={Link}
                      to={`/admin/artists/enrich/runs/${g.runId}`}
                      size="sm"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {g.runId.slice(0, 8)}
                    </Anchor>
                    {g.runStatus && (
                      <Badge size="sm" color={STATUS_COLOR[g.runStatus] ?? 'gray'}>
                        {g.runStatus}
                      </Badge>
                    )}
                    {g.promptSlug && (
                      <Text size="xs" c="dimmed">
                        {g.promptSlug}@{g.promptVersion}
                      </Text>
                    )}
                  </Group>
                  <Text size="xs" c="dimmed">
                    {g.runCreatedAt ?? ''}
                  </Text>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap="sm">
                  {g.cells.map((c) => (
                    <CellSection key={c.cell_id} cell={c} />
                  ))}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      )}
    </Drawer>
  );
}

function CellSection({ cell }: { cell: ArtistHistoryCell }) {
  const { t } = useTranslation();
  const hasParsed = cell.parsed != null && typeof cell.parsed === 'object';
  return (
    <Stack gap="xs">
      <Group gap="xs">
        <Badge size="sm" variant="light">
          {cell.vendor}
        </Badge>
        <Badge size="sm" color={STATUS_COLOR[cell.status] ?? 'gray'}>
          {cell.status}
        </Badge>
        {cell.model && (
          <Text size="xs" c="dimmed">
            {cell.model}
          </Text>
        )}
        {typeof cell.latency_ms === 'number' && (
          <Text size="xs" c="dimmed">
            {cell.latency_ms} ms
          </Text>
        )}
        {typeof cell.cost_usd === 'number' && (
          <Text size="xs" c="dimmed">
            ${cell.cost_usd.toFixed(4)}
          </Text>
        )}
      </Group>
      {cell.error_message && (
        <Tooltip label={cell.error_message} multiline w={400}>
          <Text size="sm" c="red" lineClamp={3}>
            {cell.error_message}
          </Text>
        </Tooltip>
      )}
      {hasParsed && (
        <Code block style={{ whiteSpace: 'pre-wrap', maxHeight: 320, overflow: 'auto' }}>
          {JSON.stringify(cell.parsed, null, 2)}
        </Code>
      )}
      {!hasParsed && !cell.error_message && (
        <Text size="xs" c="dimmed">
          {t('admin_enrichment.history.no_payload')}
        </Text>
      )}
    </Stack>
  );
}
