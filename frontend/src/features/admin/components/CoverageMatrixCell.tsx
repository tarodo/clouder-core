import { Box, Tooltip } from '@mantine/core';
import { memo } from 'react';
import type { CellState } from '../lib/cellState';

interface Props {
  styleId: number;
  styleName: string;
  weekNumber: number;
  state: CellState;
  tooltip: string;
  onClick: (styleId: number, weekNumber: number) => void;
}

const COLORS: Record<CellState, string> = {
  empty: 'var(--mantine-color-dark-6)',
  loaded: 'var(--mantine-color-green-7)',
  'loaded-custom': 'var(--mantine-color-green-7)',
  failed: 'var(--mantine-color-red-7)',
  running: 'var(--mantine-color-yellow-5)',
  'n/a': 'var(--mantine-color-dark-8)',
};

function CoverageMatrixCellInner({
  styleId,
  styleName,
  weekNumber,
  state,
  tooltip,
  onClick,
}: Props) {
  return (
    <Tooltip label={tooltip} withArrow disabled={!tooltip}>
      <Box
        component="button"
        type="button"
        aria-label={`${styleName} week ${weekNumber} ${state}`}
        onClick={() => onClick(styleId, weekNumber)}
        data-state={state}
        style={{
          width: 24,
          height: 24,
          borderRadius: 4,
          border: 'none',
          padding: 0,
          background: COLORS[state],
          outline:
            state === 'loaded-custom'
              ? '1px solid var(--mantine-color-yellow-5)'
              : undefined,
          cursor: state === 'n/a' ? 'default' : 'pointer',
          opacity: state === 'n/a' ? 0.4 : 1,
          animation: state === 'running' ? 'admin-pulse 1.4s infinite' : undefined,
        }}
      />
    </Tooltip>
  );
}

export const CoverageMatrixCell = memo(CoverageMatrixCellInner);
