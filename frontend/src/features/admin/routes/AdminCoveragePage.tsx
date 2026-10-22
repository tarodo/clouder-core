import { Alert, Group, Stack } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useCoverage } from '../hooks/useCoverage';
import { weekOfDate } from '../../../lib/saturdayWeek';
import { CoverageMatrix } from '../components/CoverageMatrix';
import { CellDetailDrawer } from '../components/CellDetailDrawer';
import { YearNavigator } from '../components/YearNavigator';
import { StyleVisibilityPopover } from '../components/StyleVisibilityPopover';
import { AutoIngestPanel } from '../components/AutoIngestPanel';
import { YoutubeSearchStatus } from '../components/YoutubeSearchStatus';
import { AnalysisStatus } from '../components/AnalysisStatus';
import { cellState, type CoverageCell } from '../lib/cellState';
import { runsTrackerStore } from '../lib/runsTracker';
import { PageHeader } from '../../../components/PageHeader';

export function AdminCoveragePage() {
  const { t } = useTranslation();
  const [year, setYear] = useState(() => weekOfDate(new Date())[0]);
  const q = useCoverage(year);
  const [active, setActive] = useState<{ styleId: number; weekNumber: number } | null>(
    null,
  );

  const styleMap = new Map<
    number,
    { name: string; cells: Map<number, CoverageCell>; youtubeReview: Map<number, number> }
  >();
  for (const s of q.data?.styles ?? []) {
    const cells = new Map<number, CoverageCell>();
    for (const c of s.cells) cells.set(c.week_number, c);
    const youtubeReview = new Map((s.youtube_weeks ?? []).map((w) => [w.week_number, w.review]));
    styleMap.set(s.style_id, { name: s.style_name, cells, youtubeReview });
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
      <PageHeader title={t('admin.coverage.title')} subtitle={t('admin.coverage.subtitle')}>
        <Group justify="space-between">
          <YearNavigator year={year} onChange={setYear} />
          {q.data && <StyleVisibilityPopover styles={q.data.styles} />}
        </Group>
      </PageHeader>
      {q.isError && <Alert color="red">{t('admin.coverage.load_failed')}</Alert>}
      {q.data && (
        <CoverageMatrix
          data={{ ...q.data, styles: q.data.styles.filter((s) => !s.is_hidden) }}
          onCellClick={(styleId, weekNumber) => setActive({ styleId, weekNumber })}
        />
      )}
      <AutoIngestPanel
        styleNames={new Map((q.data?.styles ?? []).map((s) => [s.style_id, s.style_name]))}
      />
      <YoutubeSearchStatus />
      <AnalysisStatus />
      <CellDetailDrawer
        open={active !== null}
        onClose={() => setActive(null)}
        styleId={active?.styleId ?? null}
        styleName={activeStyle?.name ?? null}
        weekYear={year}
        weekNumber={active?.weekNumber ?? null}
        state={state}
        cell={activeCell}
        youtubeReview={
          active && activeStyle ? (activeStyle.youtubeReview.get(active.weekNumber) ?? 0) : 0
        }
      />
    </Stack>
  );
}
