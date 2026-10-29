import { Box, ScrollArea, Skeleton, Text } from '@mantine/core';
import './CoverageMatrix.module.css';
import { useMemo } from 'react';
import { useStore } from 'zustand';
import { runsTrackerStore } from '../lib/runsTracker';
import type {
  AnalysisWeekStats,
  CoveragePayload,
  SpotifyWeekStats,
  YoutubeWeekStats,
} from '../hooks/useCoverage';
import { cellState, type CoverageCell } from '../lib/cellState';
import { formatSpotifyStats } from '../lib/spotifyStats';
import { formatYoutubeStats } from '../lib/youtubeStats';
import { formatAnalysisStats } from '../lib/analysisStats';
import { CoverageMatrixCell } from './CoverageMatrixCell';
import { Ghost, useGhost } from '../../../components/Ghost';

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
        <Box
          style={{
            position: 'sticky',
            left: 0,
            zIndex: 3,
            alignSelf: 'stretch',
            background: 'var(--mantine-color-body)',
          }}
        />
        {weeks.map((w) => (
          <Text key={w} size="xs" ta="center" c="dimmed">
            {w}
          </Text>
        ))}
        {data.styles.map((style) => {
          const byWeek = new Map<number, CoverageCell>();
          for (const c of style.cells) byWeek.set(c.week_number, c);
          const statsByWeek = new Map<number, SpotifyWeekStats>();
          for (const s of style.spotify_weeks ?? []) statsByWeek.set(s.week_number, s);
          const youtubeByWeek = new Map<number, YoutubeWeekStats>();
          for (const s of style.youtube_weeks ?? []) youtubeByWeek.set(s.week_number, s);
          const analysisByWeek = new Map<number, AnalysisWeekStats>();
          for (const s of style.analysis_weeks ?? []) analysisByWeek.set(s.week_number, s);
          return (
            <Row
              key={style.style_id}
              styleIdNum={style.style_id}
              styleName={style.style_name}
              weekYear={data.week_year}
              weeks={weeks}
              byWeek={byWeek}
              statsByWeek={statsByWeek}
              youtubeByWeek={youtubeByWeek}
              analysisByWeek={analysisByWeek}
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
  statsByWeek,
  youtubeByWeek,
  analysisByWeek,
  tracker,
  onCellClick,
}: {
  styleIdNum: number;
  styleName: string;
  weekYear: number;
  weeks: number[];
  byWeek: Map<number, CoverageCell>;
  statsByWeek: Map<number, SpotifyWeekStats>;
  youtubeByWeek: Map<number, YoutubeWeekStats>;
  analysisByWeek: Map<number, AnalysisWeekStats>;
  tracker: ReturnType<typeof runsTrackerStore.getState>;
  onCellClick: (styleId: number, weekNumber: number) => void;
}) {
  // A loading matrix: a plain 24px square per cell, not a button with its tooltip (300+ of them).
  const ghost = useGhost();
  return (
    <>
      <Box
        style={{
          position: 'sticky',
          left: 0,
          zIndex: 2,
          alignSelf: 'stretch',
          display: 'flex',
          alignItems: 'center',
          background: 'var(--mantine-color-body)',
          paddingRight: 8,
          // Cover the gap between rows so cells don't peek through when the
          // user scrolls horizontally and rows slide under the sticky column.
          boxShadow: '4px 0 4px -4px rgba(0, 0, 0, 0.6)',
        }}
      >
        <Ghost>
          <Text size="sm" truncate>
            {styleName}
          </Text>
        </Ghost>
      </Box>
      {weeks.map((w) => {
        if (ghost) return <Skeleton key={w} width={24} height={24} radius={4} />;
        const cell = byWeek.get(w);
        const running = tracker.isRunning(styleIdNum, weekYear, w);
        const baseLine = cell
          ? `Wk ${w} · ${cell.period_start} – ${cell.period_end} · ${cell.item_count} items${
              cell.is_custom_range ? ' · custom range' : ''
            }`
          : `Wk ${w} · empty`;
        const spotify = statsByWeek.get(w);
        const youtube = youtubeByWeek.get(w);
        const analysis = analysisByWeek.get(w);
        const statLines = [
          ...(spotify ? [formatSpotifyStats(spotify)] : []),
          ...(youtube ? [formatYoutubeStats(youtube)] : []),
          ...(analysis ? formatAnalysisStats(analysis) : []),
        ];
        const tooltip = statLines.length ? (
          <>
            {baseLine}
            {statLines.map((line) => (
              <span key={line}>
                <br />
                {line}
              </span>
            ))}
          </>
        ) : (
          baseLine
        );
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
