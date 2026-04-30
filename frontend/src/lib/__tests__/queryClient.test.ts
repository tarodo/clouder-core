import { describe, it, expect } from 'vitest';
import { ApiError } from '../../api/error';
import { createQueryClient } from '../queryClient';

describe('queryClient defaults', () => {
  it('does not retry on forbidden', () => {
    const qc = createQueryClient();
    const retry = qc.getDefaultOptions().queries?.retry as (
      count: number,
      err: unknown,
    ) => boolean;
    expect(retry(0, new ApiError('forbidden', 403, 'no'))).toBe(false);
  });

  it('does not retry on not_found', () => {
    const qc = createQueryClient();
    const retry = qc.getDefaultOptions().queries?.retry as (
      count: number,
      err: unknown,
    ) => boolean;
    expect(retry(0, new ApiError('not_found', 404, 'no'))).toBe(false);
  });

  it('retries up to twice on unknown errors', () => {
    const qc = createQueryClient();
    const retry = qc.getDefaultOptions().queries?.retry as (
      count: number,
      err: unknown,
    ) => boolean;
    const err = new ApiError('cold_start', 503, 'no');
    expect(retry(0, err)).toBe(true);
    expect(retry(1, err)).toBe(true);
    expect(retry(2, err)).toBe(false);
  });

  it('disables window-focus refetch', () => {
    const qc = createQueryClient();
    expect(qc.getDefaultOptions().queries?.refetchOnWindowFocus).toBe(false);
  });
});
