import { Alert, Stack, Title } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useCoverage } from '../hooks/useCoverage';
import { weekOfDate } from '../lib/saturdayWeek';
import { CoverageMatrix } from '../components/CoverageMatrix';
import { CellDetailDrawer } from '../components/CellDetailDrawer';
import { YearNavigator } from '../components/YearNavigator';
import { cellState, type CoverageCell } from '../lib/cellState';
import { runsTrackerStore } from '../lib/runsTracker';

export function AdminCoveragePage() {
  const { t } = useTranslation();
  const [year, setYear] = useState(() => weekOfDate(new Date())[0]);
  const q = useCoverage(year);
  const [active, setActive] = useState<{ styleId: number; weekNumber: number } | null>(
    null,
  );

  const styleMap = new Map<number, { name: string; cells: Map<number, CoverageCell> }>();
  for (const s of q.data?.styles ?? []) {
    const cells = new Map<number, CoverageCell>();
    for (const c of s.cells) cells.set(c.week_number, c);
    styleMap.set(s.style_id, { name: s.style_name, cells });
  }
  const activeStyle = active ? styleMap.get(active.styleId) : null;
  const activeCell =
    active && activeStyle ? (activeStyle.cells.get(active.weekNumber) ?? null) : null;
  const isRunning = !!(
    active &&
    runsTrackerStore.getState().isRunning(active.styleId, year, active.weekNumber)
  );
  const state = activeCell ? cellState(activeCell, isRunning) : isRunning ? 'running' : 'empty';

  return (
    <Stack>
      <Title order={2}>{t('admin.coverage.title')}</Title>
      <YearNavigator year={year} onChange={setYear} />
      {q.isError && <Alert color="red">{t('admin.coverage.load_failed')}</Alert>}
      {q.data && (
        <CoverageMatrix
          data={q.data}
          onCellClick={(styleId, weekNumber) => setActive({ styleId, weekNumber })}
        />
      )}
      <CellDetailDrawer
        open={active !== null}
        onClose={() => setActive(null)}
        styleId={active?.styleId ?? null}
        styleName={activeStyle?.name ?? null}
        weekYear={year}
        weekNumber={active?.weekNumber ?? null}
        state={state}
        cell={activeCell}
      />
    </Stack>
  );
}
