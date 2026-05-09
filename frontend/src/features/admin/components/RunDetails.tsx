import { Alert, Badge, Group, Stack, Text } from '@mantine/core';
import type { CoverageCell } from '../lib/cellState';

interface Props {
  cell: CoverageCell;
  errorCode?: string | null;
  errorMessage?: string | null;
}

export function RunDetails({ cell, errorCode, errorMessage }: Props) {
  return (
    <Stack gap="xs">
      <Group gap="xs">
        <Text fw={600}>{cell.period_start} – {cell.period_end}</Text>
        {cell.is_custom_range && <Badge color="yellow">custom range</Badge>}
      </Group>
      <Text size="sm" c="dimmed">
        Started {cell.started_at}
        {cell.finished_at ? ` · finished ${cell.finished_at}` : ''}
      </Text>
      <Text size="sm">
        {cell.item_count} items · status <code>{cell.status}</code>
      </Text>
      {errorCode && (
        <Alert color="red" title={errorCode}>
          {errorMessage}
        </Alert>
      )}
    </Stack>
  );
}
