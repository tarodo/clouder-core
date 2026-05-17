# Frontend Testing Guide

## Test stack

| Tool | Version | Role |
|------|---------|------|
| Vitest | ^2.1 | test runner, coverage (v8) |
| jsdom | ^25 | browser environment |
| MSW | ^2.6 | HTTP mock server (node adapter) |
| React Testing Library | ^16 | component rendering + queries |
| `@testing-library/jest-dom` | ^6.6 | DOM matchers (`toBeInTheDocument`, etc.) |
| Mantine 9 | — | UI components; requires shims (see below) |

Run all tests:

```bash
cd frontend
NODE_OPTIONS=--no-experimental-webstorage pnpm test
```

The `NODE_OPTIONS` flag is embedded in `package.json` `test` script — running `pnpm test` sets it automatically. Do not run `vitest` directly without it.

Config: `frontend/vite.config.ts` (test section). jsdom base URL is `http://localhost/` (required for MSW + `apiClient` origin matching). Setup file: `frontend/src/test/setup.ts`.

## Setup shims

`frontend/src/test/setup.ts` applies six shims in order. Each fixes a specific incompatibility.

### 1. `NODE_OPTIONS=--no-experimental-webstorage`

**Symptom fixed**: Node 25 ships a built-in `localStorage` / `sessionStorage` implementation under the `--experimental-webstorage` flag (on by default in some builds). It conflicts with jsdom's own `localStorage` implementation, causing `localStorage is not defined` or prototype-mismatch errors in tests that access storage.

**Where**: `package.json` test scripts, not `setup.ts`.

### 2. `notifyManager.setScheduler(queueMicrotask)`

**Symptom fixed**: TanStack Query 5 + React 19 + `act()` race. By default `notifyManager` schedules state notifications via `setTimeout(0)`. In tests, `act()` only flushes microtasks — the `setTimeout` callback fires **after** `act()` returns, leaving `result.current.data` as `undefined` even after `await act(async () => { await mutateAsync(...) })`.

**Fix**: switch the scheduler to `queueMicrotask` so notifications land inside `act()`'s microtask drain.

`frontend/src/test/setup.ts:14`

### 3. `import '../i18n'`

**Symptom fixed**: components that call `useTranslation()` throw `"i18next is not initialized"` (or silently return empty strings) when the i18n singleton has not been set up before the first render.

**Fix**: importing `frontend/src/i18n.ts` once in `setup.ts` initialises the singleton for the entire test process.

`frontend/src/test/setup.ts:7`

### 4. `ResizeObserver` + `Element.prototype.scrollIntoView` stubs

**Symptom fixed**: Mantine 9 `Select` and `Combobox` internally create a `ResizeObserver` on the scroll container and call `scrollIntoView` on the highlighted option. jsdom provides neither. Tests throw `ResizeObserver is not defined` and `scrollIntoView is not a function`.

**Fix**: no-op class for `ResizeObserver`; no-op function assigned to `Element.prototype.scrollIntoView`.

`frontend/src/test/setup.ts:48`–`61`

### 5. `Element.prototype.getBoundingClientRect` stub + non-zero `window.innerWidth/Height`

**Symptom fixed**: jsdom returns zero-dimension bounding rects for every element. Floating UI's `hide()` middleware (used by Mantine `Popover`, `Menu`, `Select` dropdowns) sees a zero-size reference and marks the reference as `referenceHidden`. Mantine injects `display: none` on the dropdown. `getByRole('menuitem')` cannot find the items even after clicking the trigger.

Additionally, jsdom's `window.innerWidth` and `window.innerHeight` default to 0, which Floating UI uses to compute clipping ancestors — also leading to `referenceHidden`.

**Fix**: `getBoundingClientRect` returns a 1024×1024 rect when native returns 0×0; `window.innerWidth` = 1024, `window.innerHeight` = 768.

`frontend/src/test/setup.ts:71`–`103`

### Additional shims in setup.ts (not in CLAUDE.md checklist)

- **`Request` constructor proxy**: MSW's `@mswjs/interceptors` validates `init.signal` against undici's `AbortSignal`; jsdom's `AbortSignal` fails the check. The proxy silently drops the `signal` from `RequestInit` when the native constructor rejects it.
- **`document.fonts` stub**: Mantine `Textarea` autosize calls `document.fonts.addEventListener`; jsdom has no `document.fonts`.
- **`window.matchMedia` mock**: Mantine reads `matchMedia` for color-scheme detection; jsdom has no implementation.

## Mantine in tests

### `MantineProvider` required

Any test that mounts a `Modal` or `Notifications` (including toast notifications) must wrap the component tree in `<MantineProvider theme={testTheme}>`.

`testTheme` is defined in `frontend/src/test/theme.ts`. It disables transition durations to prevent jsdom portal-animation races where portals mount/unmount asynchronously and assertions fire before the DOM settles.

### Portal singleton survives RTL `cleanup()`

`data-mantine-shared-portal-node` is attached to `document.body` once and persists across test boundaries. After `cleanup()`, stale buttons from a prior test's modal may still be in the portal.

Pattern: scope queries inside dialogs with `within`:

```ts
const dialog = await screen.findByRole('dialog');
const button = within(dialog).getByRole('button', { name: 'Confirm' });
```

Do NOT use `screen.getAllByRole('button', { name: 'X' })` without scoping — it will match buttons from prior tests' portals.

## MSW conventions

`frontend/src/test/handlers.ts` — default handlers registered in `setup.ts`.

- URL origin must be `http://localhost` (jsdom default `window.location.origin`).
- `apiClient` builds `${baseUrl}${path}` from `window.location.origin`, so handlers must match the same host.
- Do NOT invent hosts like `https://api.test`.

Example handler:

```ts
import { http, HttpResponse } from 'msw';

http.get('http://localhost/categories', () => {
  return HttpResponse.json({ items: [] });
});
```

Per-test overrides use `server.use(handler)`. Handlers reset after each test via `afterEach(() => server.resetHandlers())`.

## Vitest typed mocks

Vitest 2.x broke the legacy tuple-parameter form for `vi.fn`:

```ts
// WRONG — compiles as `never`, fails typecheck on Vitest 2.x
const mock = vi.fn<[], Promise<MyType>>();

// CORRECT — function-type form
const mock = vi.fn<() => Promise<MyType>>();
```

Apply this to all typed mocks, including module mocks created via `vi.spyOn`.
