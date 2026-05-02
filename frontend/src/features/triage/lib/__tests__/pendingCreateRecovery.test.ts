import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { schedulePendingCreateRecovery } from '../pendingCreateRecovery';

describe('schedulePendingCreateRecovery', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('fires onSuccess when first refetch finds matching block', async () => {
    const refetch = vi.fn(async () => {
      return [{ items: [{ name: 'X', date_from: '2026-04-20', date_to: '2026-04-26' }], total: 1 }];
    });
    const onSuccess = vi.fn();
    const onFailure = vi.fn();

    schedulePendingCreateRecovery({
      payload: { name: 'X', date_from: '2026-04-20', date_to: '2026-04-26' },
      refetchAllTabs: refetch,
      onSuccess,
      onFailure,
    });

    await vi.advanceTimersByTimeAsync(0);
    await Promise.resolve();
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(onFailure).not.toHaveBeenCalled();

    // later ticks must NOT fire onSuccess again
    await vi.advanceTimersByTimeAsync(15_000);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it('fires onFailure on the third tick when no match', async () => {
    const refetch = vi.fn(async () => [{ items: [], total: 0 }]);
    const onSuccess = vi.fn();
    const onFailure = vi.fn();

    schedulePendingCreateRecovery({
      payload: { name: 'X', date_from: '2026-04-20', date_to: '2026-04-26' },
      refetchAllTabs: refetch,
      onSuccess,
      onFailure,
    });

    await vi.advanceTimersByTimeAsync(0);
    await Promise.resolve();
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(onFailure).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(15_000);
    await Promise.resolve();
    expect(refetch).toHaveBeenCalledTimes(2);
    expect(onFailure).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(15_000);
    await Promise.resolve();
    expect(refetch).toHaveBeenCalledTimes(3);
    expect(onFailure).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it('matches on later tick if block appears late', async () => {
    let call = 0;
    const refetch = vi.fn(async () => {
      call++;
      if (call < 3) return [{ items: [], total: 0 }];
      return [{ items: [{ name: 'X', date_from: '2026-04-20', date_to: '2026-04-26' }], total: 1 }];
    });
    const onSuccess = vi.fn();
    const onFailure = vi.fn();

    schedulePendingCreateRecovery({
      payload: { name: 'X', date_from: '2026-04-20', date_to: '2026-04-26' },
      refetchAllTabs: refetch,
      onSuccess,
      onFailure,
    });

    await vi.advanceTimersByTimeAsync(0);
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(15_000);
    await Promise.resolve();
    expect(onSuccess).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(15_000);
    await Promise.resolve();
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(onFailure).not.toHaveBeenCalled();
  });
});
