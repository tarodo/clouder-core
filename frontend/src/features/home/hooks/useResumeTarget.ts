import { useMemo } from 'react';
import {
  readLastCurateStyle,
  readLastCurateLocation,
  clearLastCurateLocation,
} from '../../curate/lib/lastCurateLocation';
import type { TriageBlockSummary } from '../../triage/hooks/useTriageBlocksByStyle';

const STALE_MS = 7 * 24 * 60 * 60 * 1000;

export type ResumeSession = {
  styleId: string;
  blockId: string;
  bucketId: string;
};

export type ResumeTarget =
  | { kind: 'curate'; session: ResumeSession; block: TriageBlockSummary }
  | { kind: 'triage'; block: TriageBlockSummary }
  | { kind: 'empty' };

export function useResumeTarget(
  activeBlocks: TriageBlockSummary[],
  blocksByStyle: Record<string, TriageBlockSummary[]>,
): ResumeTarget {
  return useMemo(() => {
    const fallback = (): ResumeTarget =>
      activeBlocks[0]
        ? { kind: 'triage', block: activeBlocks[0] }
        : { kind: 'empty' };

    const styleId = readLastCurateStyle();
    if (!styleId) return fallback();

    const loc = readLastCurateLocation(styleId);
    if (!loc) return fallback();

    const updatedAtMs = new Date(loc.updatedAt).getTime();
    if (Number.isNaN(updatedAtMs) || Date.now() - updatedAtMs > STALE_MS) {
      clearLastCurateLocation(styleId);
      return fallback();
    }

    const block = blocksByStyle[styleId]?.find((b) => b.id === loc.blockId);
    if (!block || block.status !== 'IN_PROGRESS') {
      clearLastCurateLocation(styleId);
      return fallback();
    }

    return {
      kind: 'curate',
      session: { styleId, blockId: loc.blockId, bucketId: loc.bucketId },
      block,
    };
  }, [activeBlocks, blocksByStyle]);
}
