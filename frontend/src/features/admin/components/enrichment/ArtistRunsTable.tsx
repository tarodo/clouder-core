import { Table, Anchor, Group, CopyButton, ActionIcon, Badge } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { IconCopy } from '@tabler/icons-react';
import type { RunSummary } from '../../../../api/artists';
import { RunStatusBadge } from './RunStatusBadge';
import { GhostTd } from '../../../../components/Ghost';

/** Rows of a loading runs list's ghost. */
export function ghostRuns(n: number): RunSummary[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `ghost-${i}-0000-0000-0000-000000000000`,
    status: 'completed',
    source: 'manual',
    created_at: '2026-01-01T00:00:00Z',
    cells_ok: 3,
    cells_error: 0,
    cells_total: 3,
    cost_usd: 0.0042,
  }));
}

export function ArtistRunsTable({ items }: { items: RunSummary[] }) {
  const { t } = useTranslation();
  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('admin_enrichment.runs.col_created')}</Table.Th>
          <Table.Th>{t('admin_enrichment.runs.col_id')}</Table.Th>
          <Table.Th>{t('admin_enrichment.runs.col_status')}</Table.Th>
          <Table.Th>{t('admin_enrichment.runs.col_source')}</Table.Th>
          <Table.Th>{t('admin_enrichment.runs.col_cells')}</Table.Th>
          <Table.Th>{t('admin_enrichment.runs.col_cost')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {items.map((r) => (
          <Table.Tr key={r.id}>
            <GhostTd>{r.created_at ?? '—'}</GhostTd>
            <GhostTd>
              <Group gap={4}>
                <Anchor component={Link} to={`/admin/artists/enrich/runs/${r.id}`}>
                  {r.id.slice(0, 8)}
                </Anchor>
                <CopyButton value={r.id}>
                  {({ copy }) => (
                    <ActionIcon variant="subtle" onClick={copy} aria-label="copy id">
                      <IconCopy size={14} />
                    </ActionIcon>
                  )}
                </CopyButton>
              </Group>
            </GhostTd>
            <GhostTd><RunStatusBadge status={r.status} /></GhostTd>
            <GhostTd>
              {r.source ? (
                <Badge variant="light" color={r.source === 'auto' ? 'blue' : 'gray'}>
                  {r.source}
                </Badge>
              ) : '—'}
            </GhostTd>
            <GhostTd>{r.cells_ok}/{r.cells_error}/{r.cells_total}</GhostTd>
            <GhostTd>{typeof r.cost_usd === 'number' ? `$${r.cost_usd.toFixed(4)}` : '—'}</GhostTd>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
