import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { handlers } from './handlers';
import { notifyManager } from '@tanstack/react-query';
import '../i18n';

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

// jsdom returns zero-dimension bounding rects for every element, which makes
// Floating UI's `hide` middleware mark Mantine Popover references as
// `referenceHidden`. Mantine then injects `display: none` on the dropdown
// (PopoverDropdown uses `ctx.referenceHidden ? { display: 'none' } : null`),
// so opened menus stay hidden in the accessibility tree and `getByRole(
// 'menuitem')` cannot find them. Stub a non-zero rect so the dropdown stays
// visible after click.
const NativeGetBoundingClientRect = Element.prototype.getBoundingClientRect;
Element.prototype.getBoundingClientRect = function getBoundingClientRect() {
  const rect = NativeGetBoundingClientRect.call(this);
  if (rect.width === 0 && rect.height === 0) {
    return {
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      bottom: 1024,
      right: 1024,
      width: 1024,
      height: 1024,
      toJSON() {
        return this;
      },
    } as DOMRect;
  }
  return rect;
};

// jsdom's window has 0 inner dimensions, which Floating UI's `hide()` middleware
// uses to compute clipping ancestors. Set non-zero values so popovers aren't
// flagged `referenceHidden`.
Object.defineProperty(window, 'innerWidth', { writable: true, value: 1024 });
Object.defineProperty(window, 'innerHeight', { writable: true, value: 768 });
Object.defineProperty(document.documentElement, 'clientWidth', {
  configurable: true,
  value: 1024,
});
Object.defineProperty(document.documentElement, 'clientHeight', {
  configurable: true,
  value: 768,
});

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
