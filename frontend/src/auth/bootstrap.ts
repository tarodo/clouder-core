let resolveFn: (() => void) | null = null;
let promise: Promise<void> = new Promise((resolve) => {
  resolveFn = resolve;
});
let completed = false;

export function bootstrapPromise(): Promise<void> {
  return promise;
}

export function completeBootstrap(): void {
  if (completed) return;
  completed = true;
  resolveFn?.();
}

export function resetBootstrapForTests(): void {
  completed = false;
  promise = new Promise((resolve) => {
    resolveFn = resolve;
  });
}
