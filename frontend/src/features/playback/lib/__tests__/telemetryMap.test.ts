import { describe, expect, it } from 'vitest';
import type { QueueStatus } from '../types';
import { statusTransitionEvent } from '../telemetryMap';

describe('statusTransitionEvent', () => {
  it.each<[QueueStatus, QueueStatus, string | null]>([
    ['playing', 'paused', 'playback_pause'],
    ['buffering', 'paused', 'playback_pause'],
    ['playing', 'disconnected', 'playback_pause'],
    ['playing', 'error', 'playback_pause'],
    ['paused', 'playing', 'playback_resume'],
    ['paused', 'buffering', 'playback_resume'],
    ['disconnected', 'playing', 'playback_resume'],
    ['playing', 'ended', 'playback_ended'],
    ['paused', 'ended', 'playback_ended'],
  ])('%s → %s = %s', (prev, next, event) => {
    expect(statusTransitionEvent(prev, next)).toBe(event);
  });

  it.each<[QueueStatus, QueueStatus]>([
    ['playing', 'playing'],
    ['buffering', 'playing'], // still playing
    ['playing', 'buffering'],
    ['paused', 'loading'], // next track: its playback_play marks the boundary
    ['loading', 'playing'],
    ['idle', 'playing'],
    ['idle', 'ended'],
    ['ended', 'ended'],
  ])('%s → %s emits nothing', (prev, next) => {
    expect(statusTransitionEvent(prev, next)).toBeNull();
  });
});
