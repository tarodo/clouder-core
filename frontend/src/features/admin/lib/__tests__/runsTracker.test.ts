import { describe, expect, it } from 'vitest';
import { runsTrackerStore, type RunMeta } from '../runsTracker';

const meta = (run_id: string, week_number = 5): RunMeta => ({
  run_id,
  styleId: 1,
  weekYear: 2026,
  weekNumber: week_number,
  startedAt: Date.now(),
});

describe('runsTracker', () => {
  it('add → list → remove', () => {
    runsTrackerStore.getState().clear();
    runsTrackerStore.getState().add(meta('r1'));
    runsTrackerStore.getState().add(meta('r2'));
    expect(runsTrackerStore.getState().runs.size).toBe(2);
    runsTrackerStore.getState().remove('r1');
    expect(runsTrackerStore.getState().runs.has('r1')).toBe(false);
    expect(runsTrackerStore.getState().runs.has('r2')).toBe(true);
  });

  it('isRunning returns true for matching cell', () => {
    runsTrackerStore.getState().clear();
    runsTrackerStore.getState().add(meta('r1', 5));
    expect(runsTrackerStore.getState().isRunning(1, 2026, 5)).toBe(true);
    expect(runsTrackerStore.getState().isRunning(2, 2026, 5)).toBe(false);
    expect(runsTrackerStore.getState().isRunning(1, 2026, 6)).toBe(false);
  });

  it('clear empties the runs map', () => {
    runsTrackerStore.getState().add(meta('r1'));
    runsTrackerStore.getState().clear();
    expect(runsTrackerStore.getState().runs.size).toBe(0);
  });
});
