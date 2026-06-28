import { useEffect } from 'react';
import { telemetry } from './sdk';

export function useTelemetry(): typeof telemetry {
  return telemetry;
}

/** Stamp `context.route` for events fired while this route is mounted. */
export function useTelemetryRoute(route: string): void {
  useEffect(() => {
    telemetry.setRoute(route);
    return () => telemetry.setRoute(null);
  }, [route]);
}

/**
 * Track a row's view lifecycle: start the dwell timer + count it toward the
 * session seen-set on mount, emit `track_view` with dwell_ms on unmount/exit.
 */
export function useTrackView(trackId: string): void {
  useEffect(() => {
    telemetry.markShown(trackId);
    telemetry.markSeen(trackId);
    return () => {
      telemetry.track('track_view', { track_id: trackId, dwell_ms: telemetry.msSinceShown(trackId) });
    };
  }, [trackId]);
}
