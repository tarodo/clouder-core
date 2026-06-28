import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import { telemetry } from './sdk';
import { useTelemetry, useTelemetryRoute, useTrackView } from './hooks';

describe('telemetry hooks', () => {
  beforeEach(() => vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true'));
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('useTelemetry returns the singleton', () => {
    let captured: unknown;
    function Probe() {
      captured = useTelemetry();
      return null;
    }
    render(<Probe />);
    expect(captured).toBe(telemetry);
  });

  it('useTelemetryRoute sets the route on mount and clears it on unmount', () => {
    const setRoute = vi.spyOn(telemetry, 'setRoute');
    function Probe() {
      useTelemetryRoute('/curate/:styleId/:blockId/:bucketId');
      return null;
    }
    const { unmount } = render(<Probe />);
    expect(setRoute).toHaveBeenCalledWith('/curate/:styleId/:blockId/:bucketId');
    unmount();
    expect(setRoute).toHaveBeenLastCalledWith(null);
  });

  it('useTrackView marks shown+seen on mount and emits track_view on unmount', () => {
    const track = vi.spyOn(telemetry, 'track');
    const markSeen = vi.spyOn(telemetry, 'markSeen');
    function Probe() {
      useTrackView('track-42');
      return null;
    }
    const { unmount } = render(<Probe />);
    expect(markSeen).toHaveBeenCalledWith('track-42');
    expect(track).not.toHaveBeenCalled();
    unmount();
    expect(track).toHaveBeenCalledTimes(1);
    const [name, props] = track.mock.calls[0]!;
    expect(name).toBe('track_view');
    expect(props).toMatchObject({ track_id: 'track-42' });
    expect(typeof (props as { dwell_ms: number }).dwell_ms).toBe('number');
  });
});
