import { Table, Checkbox, Anchor, Tooltip, ActionIcon } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { IconHistory } from '@tabler/icons-react';
import type { BacklogLabel } from '../../../../api/labels';
import { RunStatusBadge } from './RunStatusBadge';

interface Props {
  items: BacklogLabel[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: (next: boolean) => void;
  /** Map of style slug → display name, for the Style column rendering. */
  styleNames?: Readonly<Record<string, string>>;
  onShowHistory?: (label: BacklogLabel) => void;
}

export function BacklogTable(p: Props) {
  const { t } = useTranslation();
  const allSelected = p.items.length > 0 && p.items.every((i) => p.selected.has(i.id));
  const displayStyle = (slug: string) => (p.styleNames && p.styleNames[slug]) || slug || '—';
  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>
            <Checkbox
              checked={allSelected}
              onChange={(e) => p.onToggleAll(e.currentTarget.checked)}
              aria-label="select all rows on this page"
            />
          </Table.Th>
          <Table.Th>{t('admin_enrichment.backlog.col_name')}</Table.Th>
          <Table.Th>{t('admin_enrichment.backlog.col_style')}</Table.Th>
          <Table.Th>{t('admin_enrichment.backlog.col_status')}</Table.Th>
          <Table.Th>{t('admin_enrichment.backlog.col_tracks')}</Table.Th>
          <Table.Th>{t('admin_enrichment.backlog.col_last_try')}</Table.Th>
          <Table.Th aria-label="actions" />
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {p.items.map((row) => (
          <Table.Tr key={row.id}>
            <Table.Td>
              <Checkbox
                checked={p.selected.has(row.id)}
                onChange={() => p.onToggle(row.id)}
                aria-label={`select ${row.name}`}
              />
            </Table.Td>
            <Table.Td>
              <Anchor component={Link} to={`/labels/${row.id}`}>
                {row.name}
              </Anchor>
            </Table.Td>
            <Table.Td>{displayStyle(row.style)}</Table.Td>
            <Table.Td>
              <RunStatusBadge status={row.status} />
            </Table.Td>
            <Table.Td>{row.track_count}</Table.Td>
            <Table.Td>{row.last_attempted_at ?? '—'}</Table.Td>
            <Table.Td>
              {p.onShowHistory && (
                <Tooltip label={t('admin_enrichment.history.title')}>
                  <ActionIcon
                    variant="subtle"
                    aria-label={`history ${row.name}`}
                    onClick={() => p.onShowHistory?.(row)}
                  >
                    <IconHistory size={16} />
                  </ActionIcon>
                </Tooltip>
              )}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
