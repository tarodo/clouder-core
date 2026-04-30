import { describe, it, expect } from 'vitest';
import { bootstrapPromise, completeBootstrap, resetBootstrapForTests } from '../bootstrap';

describe('bootstrapPromise', () => {
  it('resolves once completeBootstrap is called', async () => {
    resetBootstrapForTests();
    let resolved = false;
    void bootstrapPromise().then(() => {
      resolved = true;
    });
    expect(resolved).toBe(false);
    completeBootstrap();
    await bootstrapPromise();
    expect(resolved).toBe(true);
  });

  it('resolves immediately if already completed', async () => {
    resetBootstrapForTests();
    completeBootstrap();
    await expect(bootstrapPromise()).resolves.toBeUndefined();
  });
});
