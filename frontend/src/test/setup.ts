import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { handlers } from './handlers';
import { notifyManager } from '@tanstack/react-query';

// React Query uses setTimeout(0) by default to schedule state notifications.
// In tests, `act` only flushes microtasks — setTimeout callbacks fire after `act`
// returns, so `result.current.data` stays undefined after `await act(async () =>
// { await mutateAsync(...) })`. Switch to queueMicrotask so notifications land
// inside `act`'s microtask drain, matching the spec test pattern.
notifyManager.setScheduler(queueMicrotask);

// jsdom installs its own AbortController/AbortSignal; Node's `Request`
// constructor (used internally by react-router 7's data router and by
// @mswjs/interceptors) validates `init.signal` against undici's bundled
// AbortSignal class and rejects jsdom's instances. Wrap the global
// Request constructor so any non-undici signal is dropped silently —
// tests don't need request cancellation, just navigation to succeed.
//
// See: https://github.com/mswjs/msw/issues/1796
const NativeRequest = globalThis.Request;
const probe = new globalThis.AbortController().signal;
let signalValid = true;
try {
  new NativeRequest('http://probe/', { signal: probe });
} catch {
  signalValid = false;
}
if (!signalValid) {
  globalThis.Request = new Proxy(NativeRequest, {
    construct(target, args, newTarget) {
      const [input, init] = args as [RequestInfo | URL, RequestInit | undefined];
      if (init && 'signal' in init) {
        const stripped: RequestInit = { ...init };
        delete stripped.signal;
        return Reflect.construct(target, [input, stripped], newTarget);
      }
      return Reflect.construct(target, args, newTarget);
    },
  });
}

// jsdom does not implement ResizeObserver; Mantine's ScrollArea (used inside
// Select dropdown) calls it on mount. Provide a no-op stub so tests don't throw.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// jsdom does not implement Element.prototype.scrollIntoView; Mantine's Combobox
// calls it in a setTimeout after selection. Provide a no-op to prevent the
// "scrollIntoView is not a function" unhandled error after test cleanup.
if (typeof Element.prototype.scrollIntoView === 'undefined') {
  Element.prototype.scrollIntoView = () => {};
}

// jsdom does not implement window.matchMedia; Mantine reads it for color scheme.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

export const server = setupServer(...handlers);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => server.close());
