import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { handlers } from './handlers';

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
