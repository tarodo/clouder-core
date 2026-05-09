import { useEffect, useRef } from 'react';
import { notifications } from '@mantine/notifications';
import { useStore } from 'zustand';
import { runsTrackerStore } from '../lib/runsTracker';

export function RunProgressToast() {
  const tracker = useStore(runsTrackerStore);
  const toastIds = useRef(new Map<string, string>());

  useEffect(() => {
    // Add toasts for new runs.
    for (const meta of tracker.runs.values()) {
      if (toastIds.current.has(meta.run_id)) continue;
      const id = notifications.show({
        loading: true,
        title: 'Beatport ingest',
        message: `style ${meta.styleId} · Wk ${meta.weekNumber} · running…`,
        autoClose: false,
        withCloseButton: false,
      });
      toastIds.current.set(meta.run_id, id);
    }
    // Settle removed runs.
    for (const [runId, id] of toastIds.current.entries()) {
      if (tracker.runs.has(runId)) continue;
      notifications.update({
        id,
        title: 'Beatport ingest',
        message: 'completed',
        color: 'green',
        loading: false,
        autoClose: 4000,
      });
      toastIds.current.delete(runId);
    }
  }, [tracker.runs]);

  return null;
}
