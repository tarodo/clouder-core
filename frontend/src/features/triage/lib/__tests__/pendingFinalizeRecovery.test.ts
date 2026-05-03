import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  schedulePendingFinalizeRecovery,
  type PendingFinalizeBlock,
} from '../pendingFinalizeRecovery';

const inProgress: PendingFinalizeBlock = { id: 'b1', status: 'IN_PROGRESS' };
const finalized: PendingFinalizeBlock = { id: 'b1', status: 'FINALIZED' };

describe('pendingFinalizeRecovery', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('fires onSuccess when a tick observes status=FINALIZED', async () => {
    const onSuccess = vi.fn();
    const onFailure = vi.fn();
    const refetch = vi
      .fn<() => Promise<PendingFinalizeBlock>>()
      .mockResolvedValueOnce(inProgress)
      .mockResolvedValueOnce(finalized);

    schedulePendingFinalizeRecovery({
      blockId: 'b1',
      refetch,
      onSuccess,
      onFailure,
      delays: [0, 100, 100],
    });

    await vi.advanceTimersByTimeAsync(0);
    expect(onSuccess).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(100);
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(onSuccess).toHaveBeenCalledWith(finalized);
    expect(onFailure).not.toHaveBeenCalled();
  });

  it('fires onFailure on the final tick when status never flips', async () => {
    const onSuccess = vi.fn();
    const onFailure = vi.fn();
    const refetch = vi.fn<() => Promise<PendingFinalizeBlock>>().mockResolvedValue(inProgress);

    schedulePendingFinalizeRecovery({
      blockId: 'b1',
      refetch,
      onSuccess,
      onFailure,
      delays: [0, 100, 100],
    });

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(100);
    expect(onFailure).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(100);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onFailure).toHaveBeenCalledTimes(1);
  });

  it('swallows refetch errors on non-final ticks; failure on final tick error', async () => {
    const onSuccess = vi.fn();
    const onFailure = vi.fn();
    const refetch = vi
      .fn<() => Promise<PendingFinalizeBlock>>()
      .mockRejectedValueOnce(new Error('boom-1'))
      .mockRejectedValueOnce(new Error('boom-2'))
      .mockRejectedValueOnce(new Error('boom-3'));

    schedulePendingFinalizeRecovery({
      blockId: 'b1',
      refetch,
      onSuccess,
      onFailure,
      delays: [0, 100, 100],
    });

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(100);
    expect(onFailure).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(100);
    expect(onFailure).toHaveBeenCalledTimes(1);
  });

  it('does not call onSuccess twice if a later tick also reports FINALIZED', async () => {
    const onSuccess = vi.fn();
    const onFailure = vi.fn();
    const refetch = vi
      .fn<() => Promise<PendingFinalizeBlock>>()
      .mockResolvedValue(finalized);

    schedulePendingFinalizeRecovery({
      blockId: 'b1',
      refetch,
      onSuccess,
      onFailure,
      delays: [0, 100, 100],
    });

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(100);
    await vi.advanceTimersByTimeAsync(100);
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(onFailure).not.toHaveBeenCalled();
  });

  it('uses default delays [0, 15000, 15000] when not provided', async () => {
    const onSuccess = vi.fn();
    const onFailure = vi.fn();
    const refetch = vi.fn<() => Promise<PendingFinalizeBlock>>().mockResolvedValue(inProgress);

    schedulePendingFinalizeRecovery({ blockId: 'b1', refetch, onSuccess, onFailure });

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(onFailure).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(15_000);
    expect(onFailure).toHaveBeenCalledTimes(1);
  });
});
