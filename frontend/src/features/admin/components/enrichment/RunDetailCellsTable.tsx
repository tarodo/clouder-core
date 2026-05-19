import { Table, Badge, Tooltip, Text } from '@mantine/core';
import type { RunCell } from '../../../../api/labels';

export function RunDetailCellsTable({ cells }: { cells: RunCell[] }) {
  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Label</Table.Th>
          <Table.Th>Vendor</Table.Th>
          <Table.Th>Status</Table.Th>
          <Table.Th>Latency (ms)</Table.Th>
          <Table.Th>Cost</Table.Th>
          <Table.Th>Error</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {cells.map((c) => (
          <Table.Tr key={c.cell_id}>
            <Table.Td>{c.label_name}</Table.Td>
            <Table.Td>{c.vendor}</Table.Td>
            <Table.Td>
              <Badge color={c.status === 'ok' ? 'green' : 'red'}>{c.status}</Badge>
            </Table.Td>
            <Table.Td>{c.latency_ms}</Table.Td>
            <Table.Td>${c.cost_usd.toFixed(4)}</Table.Td>
            <Table.Td>
              {c.error_message ? (
                <Tooltip label={c.error_message}>
                  <Text size="sm" truncate maw={200}>{c.error_message}</Text>
                </Tooltip>
              ) : '—'}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
