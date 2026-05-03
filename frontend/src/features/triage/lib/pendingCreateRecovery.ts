export interface PendingCreatePayload {
  name: string;
  date_from: string;
  date_to: string;
}

export interface PendingPage {
  items: { name: string; date_from: string; date_to: string }[];
  total: number;
}

interface ScheduleArgs {
  payload: PendingCreatePayload;
  refetchAllTabs: () => Promise<PendingPage[]>;
  onSuccess: () => void;
  onFailure: () => void;
  delays?: number[];
}

const DEFAULT_DELAYS = [0, 15_000, 15_000];

export function schedulePendingCreateRecovery({
  payload,
  refetchAllTabs,
  onSuccess,
  onFailure,
  delays = DEFAULT_DELAYS,
}: ScheduleArgs): void {
  let resolved = false;

  const matches = (page: PendingPage) =>
    page.items.some(
      (b) =>
        b.name === payload.name &&
        b.date_from === payload.date_from &&
        b.date_to === payload.date_to,
    );

  const tickIndices = delays.map((_, idx) => idx);
  const cumulative = delays.reduce<number[]>((acc, d) => {
    acc.push((acc[acc.length - 1] ?? 0) + d);
    return acc;
  }, []);

  tickIndices.forEach((idx) => {
    const delay = cumulative[idx];
    setTimeout(async () => {
      if (resolved) return;
      try {
        const pages = await refetchAllTabs();
        if (resolved) return;
        if (pages.some(matches)) {
          resolved = true;
          onSuccess();
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
    }, delay);
  });
}
