import { Stack, Text } from '@mantine/core';
import { useCellRuns, type CellRun } from '../hooks/useCellRuns';

interface Props {
  styleId: number;
  weekYear: number;
  weekNumber: number;
  excludeRunId?: string;
}

export function RunHistoryList({ styleId, weekYear, weekNumber, excludeRunId }: Props) {
  const q = useCellRuns({ styleId, weekYear, weekNumber });
  if (q.isLoading) return <Text size="sm" c="dimmed">Loading history…</Text>;
  if (q.isError) return <Text size="sm" c="red">Failed to load history.</Text>;
  const items = (q.data?.items ?? []).filter((r) => r.run_id !== excludeRunId);
  if (items.length === 0) return null;
  return (
    <Stack gap={4}>
      <Text fw={600} size="sm">Previous runs</Text>
      {items.map((r) => (
        <RunRow key={r.run_id} run={r} />
      ))}
    </Stack>
  );
}

function RunRow({ run }: { run: CellRun }) {
  return (
    <Text size="xs" c="dimmed">
      {run.started_at} · {run.status}{' '}
      {run.error_code ? `(${run.error_code})` : `${run.item_count ?? 0} items`}
    </Text>
  );
}
