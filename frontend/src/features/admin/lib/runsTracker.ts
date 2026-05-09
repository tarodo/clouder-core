import { create } from 'zustand';

export interface RunMeta {
  run_id: string;
  styleId: number;
  weekYear: number;
  weekNumber: number;
  startedAt: number;
}

interface RunsState {
  runs: Map<string, RunMeta>;
  add: (meta: RunMeta) => void;
  remove: (run_id: string) => void;
  clear: () => void;
  isRunning: (styleId: number, weekYear: number, weekNumber: number) => boolean;
}

export const runsTrackerStore = create<RunsState>((set, get) => ({
  runs: new Map(),
  add: (meta) =>
    set((s) => {
      const next = new Map(s.runs);
      next.set(meta.run_id, meta);
      return { runs: next };
    }),
  remove: (run_id) =>
    set((s) => {
      const next = new Map(s.runs);
      next.delete(run_id);
      return { runs: next };
    }),
  clear: () => set({ runs: new Map() }),
  isRunning: (styleId, weekYear, weekNumber) => {
    for (const meta of get().runs.values()) {
      if (
        meta.styleId === styleId &&
        meta.weekYear === weekYear &&
        meta.weekNumber === weekNumber
      ) {
        return true;
      }
    }
    return false;
  },
}));
