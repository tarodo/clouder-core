import { useEffect, useRef } from 'react';
import { notifications } from '@mantine/notifications';
import { useStore } from 'zustand';
import { runsTrackerStore } from '../lib/runsTracker';

export function RunProgressToast() {
  const tracker = useStore(runsTrackerStore);
  const toastIds = useRef(new Map<string, string>());

  useEffect(() => {
    for (const meta of tracker.runs.values()) {
      if (toastIds.current.has(meta.run_id)) {
        // Already showing — settle if terminal status has been set.
        if (meta.terminalStatus) {
          const id = toastIds.current.get(meta.run_id)!;
          notifications.update({
            id,
            title: 'Beatport ingest',
            message: meta.terminalStatus === 'failed' ? 'failed' : 'completed',
            color: meta.terminalStatus === 'failed' ? 'red' : 'green',
            loading: false,
            autoClose: 4000,
          });
          toastIds.current.delete(meta.run_id);
          runsTrackerStore.getState().remove(meta.run_id);
        }
        continue;
      }
      // Show a new loading toast for a newly-tracked run.
      const id = notifications.show({
        loading: true,
        title: 'Beatport ingest',
        message: `style ${meta.styleId} · Wk ${meta.weekNumber} · running…`,
        autoClose: false,
        withCloseButton: false,
      });
      toastIds.current.set(meta.run_id, id);
    }
  }, [tracker.runs]);

  return null;
}
