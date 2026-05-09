import { Box, ScrollArea, Text } from '@mantine/core';
import './CoverageMatrix.module.css';
import { useMemo } from 'react';
import { useStore } from 'zustand';
import { runsTrackerStore } from '../lib/runsTracker';
import type { CoveragePayload } from '../hooks/useCoverage';
import { cellState, type CoverageCell } from '../lib/cellState';
import { CoverageMatrixCell } from './CoverageMatrixCell';

interface Props {
  data: CoveragePayload;
  onCellClick: (styleId: number, weekNumber: number) => void;
}

export function CoverageMatrix({ data, onCellClick }: Props) {
  const tracker = useStore(runsTrackerStore);
  const weeks = useMemo(
    () => Array.from({ length: data.weeks_in_year }, (_, i) => i + 1),
    [data.weeks_in_year],
  );

  return (
    <ScrollArea offsetScrollbars>
      <Box
        style={{
          display: 'grid',
          gridTemplateColumns: `160px repeat(${data.weeks_in_year}, 24px)`,
          gap: 4,
          alignItems: 'center',
        }}
      >
        <Box style={{ position: 'sticky', left: 0, background: 'var(--mantine-color-body)' }} />
        {weeks.map((w) => (
          <Text key={w} size="xs" ta="center" c="dimmed">
            {w}
          </Text>
        ))}
        {data.styles.map((style) => {
          const byWeek = new Map<number, CoverageCell>();
          for (const c of style.cells) byWeek.set(c.week_number, c);
          return (
            <Row
              key={style.style_id}
              styleIdNum={Number(style.style_id) || 0}
              styleName={style.style_name}
              weekYear={data.week_year}
              weeks={weeks}
              byWeek={byWeek}
              tracker={tracker}
              onCellClick={onCellClick}
            />
          );
        })}
      </Box>
    </ScrollArea>
  );
}

function Row({
  styleIdNum,
  styleName,
  weekYear,
  weeks,
  byWeek,
  tracker,
  onCellClick,
}: {
  styleIdNum: number;
  styleName: string;
  weekYear: number;
  weeks: number[];
  byWeek: Map<number, CoverageCell>;
  tracker: ReturnType<typeof runsTrackerStore.getState>;
  onCellClick: (styleId: number, weekNumber: number) => void;
}) {
  return (
    <>
      <Text
        size="sm"
        truncate
        style={{
          position: 'sticky',
          left: 0,
          background: 'var(--mantine-color-body)',
          paddingRight: 8,
        }}
      >
        {styleName}
      </Text>
      {weeks.map((w) => {
        const cell = byWeek.get(w);
        const running = tracker.isRunning(styleIdNum, weekYear, w);
        const tooltip = cell
          ? `Wk ${w} · ${cell.period_start} – ${cell.period_end} · ${cell.item_count} items${
              cell.is_custom_range ? ' · custom range' : ''
            }`
          : `Wk ${w} · empty`;
        return (
          <CoverageMatrixCell
            key={w}
            styleId={styleIdNum}
            styleName={styleName}
            weekNumber={w}
            state={cellState(cell, running)}
            tooltip={tooltip}
            onClick={onCellClick}
          />
        );
      })}
    </>
  );
}
