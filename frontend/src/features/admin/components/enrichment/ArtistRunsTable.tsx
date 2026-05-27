import { Table, Anchor, Group, CopyButton, ActionIcon, Badge } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { IconCopy } from '@tabler/icons-react';
import type { RunSummary } from '../../../../api/artists';
import { RunStatusBadge } from './RunStatusBadge';

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
            <Table.Td>{r.created_at ?? '—'}</Table.Td>
            <Table.Td>
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
            </Table.Td>
            <Table.Td><RunStatusBadge status={r.status} /></Table.Td>
            <Table.Td>
              {r.source ? (
                <Badge variant="light" color={r.source === 'auto' ? 'blue' : 'gray'}>
                  {r.source}
                </Badge>
              ) : '—'}
            </Table.Td>
            <Table.Td>{r.cells_ok}/{r.cells_error}/{r.cells_total}</Table.Td>
            <Table.Td>{typeof r.cost_usd === 'number' ? `$${r.cost_usd.toFixed(4)}` : '—'}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
