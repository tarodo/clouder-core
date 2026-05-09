import { Button, Drawer, Stack, Text } from '@mantine/core';
import { useState } from 'react';
import { saturdayWeekRange } from '../lib/saturdayWeek';
import { useRunPoller } from '../hooks/useRunPoller';
import { IngestForm } from './IngestForm';
import { RunDetails } from './RunDetails';
import { RunHistoryList } from './RunHistoryList';
import type { CellState, CoverageCell } from '../lib/cellState';

interface Props {
  open: boolean;
  onClose: () => void;
  styleId: number | null;
  styleName: string | null;
  weekYear: number;
  weekNumber: number | null;
  state: CellState;
  cell: CoverageCell | null;
}

export function CellDetailDrawer({
  open,
  onClose,
  styleId,
  styleName,
  weekYear,
  weekNumber,
  state,
  cell,
}: Props) {
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const polling = useRunPoller(
    activeRunId,
    activeRunId && styleId !== null && weekNumber !== null
      ? { styleId, weekYear, weekNumber }
      : null,
  );
  const [reingest, setReingest] = useState(false);

  if (styleId === null || styleName === null || weekNumber === null) return null;

  const [stdStart, stdEnd] = saturdayWeekRange(weekYear, weekNumber);
  const title = `${styleName} · Wk ${weekNumber} · ${stdStart
    .toISOString()
    .slice(0, 10)} – ${stdEnd.toISOString().slice(0, 10)}`;

  return (
    <Drawer opened={open} onClose={onClose} position="right" size="md" title={title}>
      <Stack gap="md">
        {state === 'empty' && (
          <IngestForm
            styleId={styleId}
            styleName={styleName}
            weekYear={weekYear}
            weekNumber={weekNumber}
            onStarted={setActiveRunId}
          />
        )}
        {state === 'failed' && cell && (
          <>
            <RunDetails
              cell={cell}
              errorCode="see history"
              errorMessage="Latest run failed; retry below."
            />
            <IngestForm
              styleId={styleId}
              styleName={styleName}
              weekYear={weekYear}
              weekNumber={weekNumber}
              onStarted={setActiveRunId}
            />
          </>
        )}
        {(state === 'loaded' || state === 'loaded-custom') && cell && (
          <>
            <RunDetails cell={cell} />
            {!reingest ? (
              <Button variant="light" onClick={() => setReingest(true)}>
                Re-ingest
              </Button>
            ) : (
              <IngestForm
                styleId={styleId}
                styleName={styleName}
                weekYear={weekYear}
                weekNumber={weekNumber}
                onStarted={setActiveRunId}
              />
            )}
          </>
        )}
        {state === 'running' && (
          <Text size="sm">
            Run in progress {activeRunId ? `(${polling.data?.status ?? 'queued'})` : '…'}
          </Text>
        )}
        <RunHistoryList
          styleId={styleId}
          weekYear={weekYear}
          weekNumber={weekNumber}
          excludeRunId={cell?.run_id}
        />
      </Stack>
    </Drawer>
  );
}
