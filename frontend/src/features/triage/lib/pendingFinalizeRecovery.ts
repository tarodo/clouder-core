export interface PendingFinalizeBlock {
  id: string;
  status: 'IN_PROGRESS' | 'FINALIZED';
}

interface ScheduleArgs {
  blockId: string;
  refetch: () => Promise<PendingFinalizeBlock>;
  onSuccess: (block: PendingFinalizeBlock) => void;
  onFailure: () => void;
  delays?: number[];
}

const DEFAULT_DELAYS = [0, 15_000, 15_000];

export function schedulePendingFinalizeRecovery({
  refetch,
  onSuccess,
  onFailure,
  delays = DEFAULT_DELAYS,
}: ScheduleArgs): void {
  let resolved = false;

  const cumulative = delays.reduce<number[]>((acc, d) => {
    acc.push((acc[acc.length - 1] ?? 0) + d);
    return acc;
  }, []);

  delays.forEach((_, idx) => {
    const total = cumulative[idx];
    setTimeout(async () => {
      if (resolved) return;
      try {
        const block = await refetch();
        if (resolved) return;
        if (block.status === 'FINALIZED') {
          resolved = true;
          onSuccess(block);
          return;
        }
        if (idx === delays.length - 1) {
          resolved = true;
          onFailure();
        }
      } catch {
        // refetch failure during recovery: silent for non-final ticks; on the final tick mark failure
        if (idx === delays.length - 1 && !resolved) {
          resolved = true;
          onFailure();
        }
      }
    }, total);
  });
}
