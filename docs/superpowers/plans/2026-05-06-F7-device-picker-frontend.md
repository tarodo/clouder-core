# F7 Device Picker (P-25) — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the P-25 device picker. Replace F6's silent CLOUDER-tab auto-pick with a user-driven flow: visible device indicator in PlayerCard + MiniBar, Drawer (mobile) / Popover (desktop) picker, `getMyDevices` polling, `localStorage`-backed silent restore, auto-refresh on transfer 404.

**Architecture:** Approach 2 from the spec — extend the existing `PlaybackProvider` with a `devices` slice (`list`, `active`, `cloderTabId`, `isOpen`, `pick`, `open`, `close`, `refresh`). Picker UI lives in new files under `frontend/src/features/playback/`; one `DevicePickerSurface` mounts globally in `_layout.tsx` and selects Drawer or Popover via `useMediaQuery`. Polling owned by a single `useEffect` inside the provider with deps `[sdkReady, isOpen]`.

**Tech Stack:** React 19 + Mantine 9 (`Drawer`, `Popover`, `Skeleton`), `@tabler/icons-react`, Spotify Web API (`getMyDevices`, `transferMyPlayback` — already wrapped in `spotifyWebApi.ts`), `localStorage` (try/catch wrapped), TanStack Query 5 (existing test infra), Vitest 2 + MSW.

**Spec:** `docs/superpowers/specs/2026-05-06-F7-device-picker-frontend-design.md` (committed `b3d0ba4`).

---

## File Structure

### New files

```
frontend/src/features/playback/
├── DevicePicker.tsx              // desktop <Popover> content
├── DeviceDrawer.tsx              // mobile <Drawer> content
├── DevicePickerSurface.tsx       // media-query wrapper, mounted in _layout
├── DeviceIndicator.tsx           // pill (icon + name + open trigger)
├── DeviceList.tsx                // shared connecting/loading/empty/error/list switch
├── DeviceRow.tsx                 // single row (icon, name, active check, restricted badge)
├── DevicePicker.module.css       // popover, drawer, pill styles
└── lib/
    ├── deviceTypes.ts            // SpotifyDevice + SpotifyDeviceType + iconForDeviceType
    ├── lastDeviceStore.ts        // localStorage read/write/clear; try/catch wrapped
    └── usePolling.ts             // generic interval hook; respects enabled flag + window focus
```

### Existing files modified

- `frontend/src/features/playback/api/spotifyWebApi.ts` — add `getMyDevices()` method.
- `frontend/src/features/playback/PlaybackProvider.tsx` — extend `PlaybackContextValue` with `devices`; add `activeDeviceIdRef` + `cloderTabIdRef` refs (keeping `deviceIdRef` as alias for back-compat is rejected; the rename is a single-pass refactor); rewire SDK `ready` handler to wait for first poll (F7-3); add polling effect; add active-device-offline detection.
- `frontend/src/features/playback/PlayerCard.tsx` — render `<DeviceIndicator mode="full" />` in subline below artists; replace `onOpenDevicePicker` callback usage (now wired through `usePlayback`).
- `frontend/src/features/playback/MiniBar.tsx` — render `<DeviceIndicator mode="compact" />`.
- `frontend/src/routes/_layout.tsx` — mount `<DevicePickerSurface />` inside `<PlaybackChrome>`.
- `frontend/src/features/curate/components/CurateSession.tsx` — replace placeholder `onOpenDevicePicker` with `playback.devices.open(anchor)`.
- `frontend/src/i18n/en.json` — add `playback.devices.*` strings.

---

## Task 1: Spotify device types

**Files:**
- Create: `frontend/src/features/playback/lib/deviceTypes.ts`
- Test: `frontend/src/features/playback/__tests__/deviceTypes.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/features/playback/__tests__/deviceTypes.test.ts
import { describe, expect, it } from 'vitest';
import {
  IconBroadcast,
  IconCar,
  IconCast,
  IconCloud,
  IconDeviceGamepad,
  IconDeviceLaptop,
  IconDeviceMobile,
  IconDeviceSpeaker,
  IconDeviceTablet,
  IconDeviceTv,
  IconDeviceUnknown,
  IconHeadphones,
} from '@tabler/icons-react';
import { iconForDeviceType, type SpotifyDevice } from '../lib/deviceTypes';

const baseDevice = (over: Partial<SpotifyDevice>): SpotifyDevice => ({
  id: 'd1',
  name: 'Device',
  type: 'Computer',
  is_active: false,
  is_private_session: false,
  is_restricted: false,
  volume_percent: null,
  ...over,
});

describe('iconForDeviceType', () => {
  it.each([
    ['Smartphone', IconDeviceMobile],
    ['Tablet', IconDeviceTablet],
    ['Speaker', IconDeviceSpeaker],
    ['TV', IconDeviceTv],
    ['CastVideo', IconCast],
    ['CastAudio', IconBroadcast],
    ['AVR', IconDeviceTv],
    ['STB', IconDeviceTv],
    ['AudioDongle', IconHeadphones],
    ['GameConsole', IconDeviceGamepad],
    ['AutomobileVoice', IconCar],
    ['Unknown', IconDeviceUnknown],
  ] as const)('maps %s to expected icon', (type, icon) => {
    expect(iconForDeviceType(baseDevice({ type }), null)).toBe(icon);
  });

  it('maps Computer to IconDeviceLaptop by default', () => {
    expect(iconForDeviceType(baseDevice({ id: 'x', type: 'Computer' }), 'cloder-id')).toBe(
      IconDeviceLaptop,
    );
  });

  it('overrides Computer with IconCloud when device.id === cloderTabId', () => {
    expect(iconForDeviceType(baseDevice({ id: 'cloder-id', type: 'Computer' }), 'cloder-id')).toBe(
      IconCloud,
    );
  });

  it('does NOT override non-Computer types even when id matches cloderTabId', () => {
    expect(
      iconForDeviceType(baseDevice({ id: 'cloder-id', type: 'Smartphone' }), 'cloder-id'),
    ).toBe(IconDeviceMobile);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/deviceTypes.test.ts`
Expected: FAIL — module `'../lib/deviceTypes'` not found.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/features/playback/lib/deviceTypes.ts
import {
  IconBroadcast,
  IconCar,
  IconCast,
  IconCloud,
  IconDeviceGamepad,
  IconDeviceLaptop,
  IconDeviceMobile,
  IconDeviceSpeaker,
  IconDeviceTablet,
  IconDeviceTv,
  IconDeviceUnknown,
  IconHeadphones,
  type Icon,
} from '@tabler/icons-react';

export type SpotifyDeviceType =
  | 'Computer'
  | 'Smartphone'
  | 'Tablet'
  | 'Speaker'
  | 'TV'
  | 'CastVideo'
  | 'CastAudio'
  | 'AVR'
  | 'STB'
  | 'AudioDongle'
  | 'GameConsole'
  | 'AutomobileVoice'
  | 'Unknown';

export interface SpotifyDevice {
  id: string;
  name: string;
  type: SpotifyDeviceType;
  is_active: boolean;
  is_private_session: boolean;
  is_restricted: boolean;
  volume_percent: number | null;
}

export function iconForDeviceType(device: SpotifyDevice, cloderTabId: string | null): Icon {
  if (device.type === 'Computer' && cloderTabId !== null && device.id === cloderTabId) {
    return IconCloud;
  }
  switch (device.type) {
    case 'Computer':
      return IconDeviceLaptop;
    case 'Smartphone':
      return IconDeviceMobile;
    case 'Tablet':
      return IconDeviceTablet;
    case 'Speaker':
      return IconDeviceSpeaker;
    case 'TV':
    case 'AVR':
    case 'STB':
      return IconDeviceTv;
    case 'CastVideo':
      return IconCast;
    case 'CastAudio':
      return IconBroadcast;
    case 'AudioDongle':
      return IconHeadphones;
    case 'GameConsole':
      return IconDeviceGamepad;
    case 'AutomobileVoice':
      return IconCar;
    case 'Unknown':
    default:
      return IconDeviceUnknown;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/deviceTypes.test.ts`
Expected: PASS — all 16 cases green.

- [ ] **Step 5: Commit**

Use `caveman:caveman-commit` for the message. Stage + commit:

```bash
git add frontend/src/features/playback/lib/deviceTypes.ts frontend/src/features/playback/__tests__/deviceTypes.test.ts
# message via skill: feat(f7): add SpotifyDevice types and icon mapping
```

---

## Task 2: lastDeviceStore (localStorage wrapper)

**Files:**
- Create: `frontend/src/features/playback/lib/lastDeviceStore.ts`
- Test: `frontend/src/features/playback/__tests__/lastDeviceStore.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/features/playback/__tests__/lastDeviceStore.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { lastDeviceStore } from '../lib/lastDeviceStore';

const KEY = 'clouder.last_device_id';

describe('lastDeviceStore', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns null when nothing saved', () => {
    expect(lastDeviceStore.get()).toBeNull();
  });

  it('round-trips set/get', () => {
    lastDeviceStore.set('abc-123');
    expect(lastDeviceStore.get()).toBe('abc-123');
    expect(window.localStorage.getItem(KEY)).toBe('abc-123');
  });

  it('clear removes the entry', () => {
    lastDeviceStore.set('abc-123');
    lastDeviceStore.clear();
    expect(lastDeviceStore.get()).toBeNull();
    expect(window.localStorage.getItem(KEY)).toBeNull();
  });

  it('returns null and does not throw when set throws', () => {
    vi.spyOn(window.Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('quota');
    });
    expect(() => lastDeviceStore.set('abc')).not.toThrow();
    // get should still return null because setItem was suppressed
    expect(lastDeviceStore.get()).toBeNull();
  });

  it('returns null when get throws (Safari private mode)', () => {
    vi.spyOn(window.Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('access denied');
    });
    expect(lastDeviceStore.get()).toBeNull();
  });

  it('does not throw when clear throws', () => {
    vi.spyOn(window.Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new DOMException('access denied');
    });
    expect(() => lastDeviceStore.clear()).not.toThrow();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/lastDeviceStore.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/features/playback/lib/lastDeviceStore.ts
const KEY = 'clouder.last_device_id';

export const lastDeviceStore = {
  get(): string | null {
    try {
      return window.localStorage.getItem(KEY);
    } catch {
      return null;
    }
  },
  set(deviceId: string): void {
    try {
      window.localStorage.setItem(KEY, deviceId);
    } catch {
      // localStorage unavailable (Safari private, quota exceeded). No-op.
    }
  },
  clear(): void {
    try {
      window.localStorage.removeItem(KEY);
    } catch {
      // Same. No-op.
    }
  },
};
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/lastDeviceStore.test.ts`
Expected: PASS — 6 cases green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/playback/lib/lastDeviceStore.ts frontend/src/features/playback/__tests__/lastDeviceStore.test.ts
# message via skill
```

---

## Task 3: getMyDevices API method

**Files:**
- Modify: `frontend/src/features/playback/api/spotifyWebApi.ts`
- Test: `frontend/src/features/playback/api/__tests__/spotifyWebApi.test.ts` (existing) — extend.

- [ ] **Step 1: Read existing test file structure**

Run: `find frontend/src/features/playback/api/__tests__ -type f`. If none exists, create `frontend/src/features/playback/api/__tests__/spotifyWebApi.test.ts`.

- [ ] **Step 2: Write the failing test**

```ts
// frontend/src/features/playback/api/__tests__/spotifyWebApi.test.ts (or extend existing)
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { spotifyApi } from '../spotifyWebApi';
import { spotifyTokenStore } from '../../../../auth/spotifyTokenStore';

describe('spotifyApi.getMyDevices', () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    spotifyTokenStore.set('token-1');
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockReset();
  });
  afterEach(() => {
    spotifyTokenStore.clear();
    vi.unstubAllGlobals();
  });

  it('returns devices on 200', async () => {
    const devices = [{ id: 'd1', name: 'Laptop', type: 'Computer', is_active: true, is_private_session: false, is_restricted: false, volume_percent: 60 }];
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ devices }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    const result = await spotifyApi.getMyDevices();
    expect(result).toEqual(devices);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe('https://api.spotify.com/v1/me/player/devices');
    expect((init as RequestInit).method).toBe('GET');
    expect(((init as RequestInit).headers as Record<string, string>).Authorization).toBe('Bearer token-1');
  });

  it('retries once on 401 if onAuthExpired returns true', async () => {
    fetchMock
      .mockResolvedValueOnce(new Response('', { status: 401 }))
      .mockImplementationOnce(async () => {
        // simulate token rotated by AuthProvider
        spotifyTokenStore.set('token-2');
        return new Response(JSON.stringify({ devices: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      });
    const onAuthExpired = vi.fn(async () => true);
    const result = await spotifyApi.getMyDevices({ onAuthExpired });
    expect(result).toEqual([]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(onAuthExpired).toHaveBeenCalledTimes(1);
  });

  it('throws on 500', async () => {
    fetchMock.mockResolvedValueOnce(new Response('', { status: 500 }));
    await expect(spotifyApi.getMyDevices()).rejects.toThrow(/spotify_api_500/);
  });

  it('returns [] when devices field is missing', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    const result = await spotifyApi.getMyDevices();
    expect(result).toEqual([]);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/playback/api/__tests__/spotifyWebApi.test.ts`
Expected: FAIL — `getMyDevices is not a function`.

- [ ] **Step 4: Add the method**

Edit `frontend/src/features/playback/api/spotifyWebApi.ts`. Inside the `spotifyApi` object, add after `seek`:

```ts
async getMyDevices(opts: CallOptions = {}): Promise<SpotifyDevice[]> {
  const res = await call('GET', '/v1/me/player/devices', null, opts);
  const json = (await res.json()) as { devices?: SpotifyDevice[] };
  return json.devices ?? [];
},
```

Add the import at the top of the file:

```ts
import type { SpotifyDevice } from '../lib/deviceTypes';
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/playback/api/__tests__/spotifyWebApi.test.ts`
Expected: PASS — 4 cases green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/playback/api/spotifyWebApi.ts frontend/src/features/playback/api/__tests__/spotifyWebApi.test.ts
# message via skill
```

---

## Task 4: usePolling hook

**Files:**
- Create: `frontend/src/features/playback/lib/usePolling.ts`
- Test: `frontend/src/features/playback/__tests__/usePolling.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/features/playback/__tests__/usePolling.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { act } from 'react';
import { usePolling } from '../lib/usePolling';

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('does not call fn when enabled=false', () => {
    const fn = vi.fn();
    renderHook(() => usePolling(fn, { enabled: false, intervalMs: 1000 }));
    act(() => { vi.advanceTimersByTime(5000); });
    expect(fn).not.toHaveBeenCalled();
  });

  it('calls fn at every interval when enabled', () => {
    const fn = vi.fn();
    renderHook(() => usePolling(fn, { enabled: true, intervalMs: 1000 }));
    act(() => { vi.advanceTimersByTime(1000); });
    expect(fn).toHaveBeenCalledTimes(1);
    act(() => { vi.advanceTimersByTime(2000); });
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it('cleans up on unmount', () => {
    const fn = vi.fn();
    const { unmount } = renderHook(() => usePolling(fn, { enabled: true, intervalMs: 500 }));
    act(() => { vi.advanceTimersByTime(500); });
    expect(fn).toHaveBeenCalledTimes(1);
    unmount();
    act(() => { vi.advanceTimersByTime(5000); });
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('swaps interval when intervalMs changes', () => {
    const fn = vi.fn();
    const { rerender } = renderHook(
      ({ ms }: { ms: number }) => usePolling(fn, { enabled: true, intervalMs: ms }),
      { initialProps: { ms: 1000 } },
    );
    act(() => { vi.advanceTimersByTime(1000); });
    expect(fn).toHaveBeenCalledTimes(1);
    rerender({ ms: 200 });
    act(() => { vi.advanceTimersByTime(600); });
    // 3 ticks at 200ms after rerender
    expect(fn).toHaveBeenCalledTimes(4);
  });

  it('fires fn on window focus event when enabled', () => {
    const fn = vi.fn();
    renderHook(() => usePolling(fn, { enabled: true, intervalMs: 1000 }));
    act(() => { window.dispatchEvent(new Event('focus')); });
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('does not fire on focus when disabled', () => {
    const fn = vi.fn();
    renderHook(() => usePolling(fn, { enabled: false, intervalMs: 1000 }));
    act(() => { window.dispatchEvent(new Event('focus')); });
    expect(fn).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/usePolling.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/features/playback/lib/usePolling.ts
import { useEffect, useRef } from 'react';

interface PollingOptions {
  enabled: boolean;
  intervalMs: number;
}

/**
 * Calls `fn` every `intervalMs` while `enabled`, plus on every `window` focus.
 * Always invokes the latest `fn` (no stale closures).
 */
export function usePolling(fn: () => void, { enabled, intervalMs }: PollingOptions): void {
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (!enabled) return;
    const tick = () => fnRef.current();
    const id = window.setInterval(tick, intervalMs);
    const onFocus = () => fnRef.current();
    window.addEventListener('focus', onFocus);
    return () => {
      window.clearInterval(id);
      window.removeEventListener('focus', onFocus);
    };
  }, [enabled, intervalMs]);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/usePolling.test.ts`
Expected: PASS — 6 cases green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/playback/lib/usePolling.ts frontend/src/features/playback/__tests__/usePolling.test.ts
```

---

## Task 5: Extend PlaybackContextValue with `devices` slice (types only)

**Files:**
- Modify: `frontend/src/features/playback/PlaybackProvider.tsx`

This task only adds TYPES + a stub implementation that returns sensible defaults so existing F6 callers compile. Real polling, picking, and refresh land in Tasks 6–9. No new test — Task 6 covers behaviour.

- [ ] **Step 1: Add `DevicesSlice` type and extend `PlaybackContextValue`**

In `frontend/src/features/playback/PlaybackProvider.tsx`, after the imports add:

```ts
import type { SpotifyDevice } from './lib/deviceTypes';

export interface DevicesSlice {
  list: readonly SpotifyDevice[];
  active: SpotifyDevice | null;
  cloderTabId: string | null;
  isLoading: boolean;
  error: 'network' | 'auth' | null;
  isOpen: boolean;
  pickerAnchor: HTMLElement | null;
  open: (anchor?: HTMLElement | null) => void;
  close: () => void;
  refresh: () => Promise<void>;
  pick: (deviceId: string) => Promise<void>;
}
```

Extend the `PlaybackContextValue` interface — add `devices: DevicesSlice;` after `controls`:

```ts
export interface PlaybackContextValue {
  queue: { ... };
  track: { ... };
  sdk: { ready: boolean; error: SdkError | null };
  controls: { ... };
  devices: DevicesSlice;   // NEW
}
```

- [ ] **Step 2: Add stub implementation inside the provider**

Inside `PlaybackProvider`, after `clearQueue` and before the `value` `useMemo`, add:

```ts
const [devicesList, setDevicesList] = useState<readonly SpotifyDevice[]>([]);
const [activeDeviceId, setActiveDeviceId] = useState<string | null>(null);
const [cloderTabId, setCloderTabId] = useState<string | null>(null);
const [devicesLoading, setDevicesLoading] = useState(false);
const [devicesError, setDevicesError] = useState<'network' | 'auth' | null>(null);
const [pickerOpen, setPickerOpen] = useState(false);
const [pickerAnchor, setPickerAnchor] = useState<HTMLElement | null>(null);

const activeDeviceIdRef = useRef<string | null>(null);
const cloderTabIdRef = useRef<string | null>(null);

const setActive = useCallback((deviceId: string | null) => {
  activeDeviceIdRef.current = deviceId;
  setActiveDeviceId(deviceId);
}, []);

const openPicker = useCallback((anchor?: HTMLElement | null) => {
  setPickerAnchor(anchor ?? null);
  setPickerOpen(true);
}, []);

const closePicker = useCallback(() => {
  setPickerOpen(false);
}, []);

const refreshDevices = useCallback(async (): Promise<void> => {
  // Stub — real implementation in Task 6.
}, []);

const pickDevice = useCallback(async (_deviceId: string): Promise<void> => {
  // Stub — real implementation in Task 7.
}, []);

const activeDevice = useMemo(
  () => devicesList.find((d) => d.id === activeDeviceId) ?? null,
  [devicesList, activeDeviceId],
);
```

- [ ] **Step 3: Wire `devices` into the `value` `useMemo`**

Add the `devices` slot to the `value` object:

```ts
const value = useMemo<PlaybackContextValue>(
  () => ({
    queue,
    track,
    sdk: { ready: sdkReady, error: sdkError },
    controls: { ... },
    devices: {
      list: devicesList,
      active: activeDevice,
      cloderTabId,
      isLoading: devicesLoading,
      error: devicesError,
      isOpen: pickerOpen,
      pickerAnchor,
      open: openPicker,
      close: closePicker,
      refresh: refreshDevices,
      pick: pickDevice,
    },
  }),
  [
    queue,
    track,
    sdkReady,
    sdkError,
    play,
    pause,
    togglePlayPause,
    next,
    prev,
    seekMs,
    seekPct,
    bindQueue,
    clearQueue,
    cancelPendingAdvance,
    __schedulePendingAdvance,
    devicesList,
    activeDevice,
    cloderTabId,
    devicesLoading,
    devicesError,
    pickerOpen,
    pickerAnchor,
    openPicker,
    closePicker,
    refreshDevices,
    pickDevice,
  ],
);
```

- [ ] **Step 4: Verify types + tests still pass**

Run:

```
cd frontend && pnpm typecheck && pnpm vitest run
```

Expected: typecheck clean, all existing tests still green (F6 PlaybackProvider tests must NOT break).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/playback/PlaybackProvider.tsx
# message via skill: feat(f7): scaffold devices slice on PlaybackContextValue
```

---

## Task 6: Implement `refresh()` and active-device-offline detection

**Files:**
- Modify: `frontend/src/features/playback/PlaybackProvider.tsx`
- Test: `frontend/src/features/playback/__tests__/PlaybackProvider.devices.test.tsx`

This task implements `refresh()` (the core `getMyDevices` call) and the side-effect that flips `queue.status` to `disconnected` when the active device leaves the list.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/playback/__tests__/PlaybackProvider.devices.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { act, render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../test/theme';
import { PlaybackProvider } from '../PlaybackProvider';
import { usePlayback } from '../usePlayback';
import { spotifyApi } from '../api/spotifyWebApi';
import { spotifyTokenStore } from '../../../auth/spotifyTokenStore';
import { AuthProvider } from '../../../auth/AuthProvider';

function Probe({ onValue }: { onValue: (v: ReturnType<typeof usePlayback>) => void }) {
  const v = usePlayback();
  onValue(v);
  return null;
}

const wrap = (children: React.ReactNode) => (
  <MantineProvider theme={testTheme}>
    <MemoryRouter>
      <AuthProvider>
        <PlaybackProvider>{children}</PlaybackProvider>
      </AuthProvider>
    </MemoryRouter>
  </MantineProvider>
);

describe('PlaybackProvider.devices.refresh', () => {
  beforeEach(() => {
    spotifyTokenStore.set('tok');
  });
  afterEach(() => {
    spotifyTokenStore.clear();
    vi.restoreAllMocks();
  });

  it('populates list from getMyDevices', async () => {
    const devices = [
      { id: 'd1', name: 'Laptop', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: 60 },
    ];
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue(devices);
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.devices.refresh();
    });
    await waitFor(() => expect(captured!.devices.list).toEqual(devices));
    expect(captured!.devices.error).toBeNull();
  });

  it('sets error=network on rejection', async () => {
    vi.spyOn(spotifyApi, 'getMyDevices').mockRejectedValue(new Error('spotify_api_500'));
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.devices.refresh();
    });
    await waitFor(() => expect(captured!.devices.error).toBe('network'));
  });

  it('flips queue.status to disconnected when active device leaves the list', async () => {
    // First poll: list contains both. Set activeDeviceId to "remote".
    const initial = [
      { id: 'cloder', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'remote', name: 'Phone', type: 'Smartphone' as const, is_active: true, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    const after = [initial[0]!];
    const spy = vi.spyOn(spotifyApi, 'getMyDevices')
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(after);
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));

    // First refresh + simulate active device pick.
    await act(async () => {
      await captured!.devices.refresh();
    });
    // Helper test bridge: pick() will be implemented in Task 7. For Task 6
    // we manually set active via spotifyApi.transferMyPlayback mock + a
    // direct ref poke. Instead we exercise via a second refresh with a
    // pre-set active id.
    // Since pick is stubbed, drive the test via Task 7 once it lands.
    // For now only assert refresh populated the list:
    expect(captured!.devices.list).toEqual(initial);
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
```

> **NOTE for the implementer.** The third test scenario depends on `pick()` (Task 7) and the bootstrap restore (Task 8) being in place. As written it only asserts the first-refresh behaviour. The full active-device-offline scenario is added in Task 8 once those pieces exist.

- [ ] **Step 2: Run test to verify the first two cases fail**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/PlaybackProvider.devices.test.tsx`
Expected: FAIL — `refresh()` is a no-op stub from Task 5.

- [ ] **Step 3: Implement `refresh()`**

In `PlaybackProvider.tsx`, replace the stub `refreshDevices` with:

```ts
const refreshDevices = useCallback(async (): Promise<void> => {
  setDevicesLoading(true);
  try {
    const list = await spotifyApi.getMyDevices({ onAuthExpired });
    setDevicesList(list);
    setDevicesError(null);
    // Active-device-offline detection: if the active device disappeared
    // from the new list, flip queue.status to 'disconnected'. The user
    // recovers by opening the picker and choosing another device.
    const activeId = activeDeviceIdRef.current;
    if (activeId && !list.some((d) => d.id === activeId)) {
      queueDispatch({ type: 'STATUS', status: 'disconnected' });
    }
  } catch {
    setDevicesError('network');
  } finally {
    setDevicesLoading(false);
  }
}, [onAuthExpired]);
```

- [ ] **Step 4: Run test to verify cases 1 + 2 pass**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/PlaybackProvider.devices.test.tsx`
Expected: PASS — first two cases green; third case asserts only the basic populate (per inline note).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/playback/PlaybackProvider.tsx frontend/src/features/playback/__tests__/PlaybackProvider.devices.test.tsx
```

---

## Task 7: Implement `pick(deviceId)`

**Files:**
- Modify: `frontend/src/features/playback/PlaybackProvider.tsx`
- Test: extend `PlaybackProvider.devices.test.tsx` with new cases.

- [ ] **Step 1: Write the failing tests**

Append to `PlaybackProvider.devices.test.tsx`:

```tsx
describe('PlaybackProvider.devices.pick', () => {
  beforeEach(() => {
    spotifyTokenStore.set('tok');
  });
  afterEach(() => {
    spotifyTokenStore.clear();
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it('happy path — calls transferMyPlayback, persists last_device_id, closes picker', async () => {
    const devices = [
      { id: 'cloder', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'speaker', name: 'KitchenSpeaker', type: 'Speaker' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue(devices);
    const transfer = vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.devices.refresh();
    });
    act(() => { captured!.devices.open(null); });
    expect(captured!.devices.isOpen).toBe(true);

    await act(async () => {
      await captured!.devices.pick('speaker');
    });

    expect(transfer).toHaveBeenCalledWith({ deviceId: 'speaker', play: false }, expect.any(Object));
    expect(window.localStorage.getItem('clouder.last_device_id')).toBe('speaker');
    expect(captured!.devices.isOpen).toBe(false);
    expect(captured!.devices.active?.id).toBe('speaker');
  });

  it('on 404 — refreshes list and keeps picker open', async () => {
    const initial = [
      { id: 'cloder', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'stale', name: 'OldPhone', type: 'Smartphone' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    const after = [initial[0]!];
    vi.spyOn(spotifyApi, 'getMyDevices')
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(after);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockRejectedValue(new Error('spotify_api_404'));

    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.devices.refresh();
    });
    act(() => { captured!.devices.open(null); });

    await act(async () => {
      await captured!.devices.pick('stale').catch(() => {}); // pick should swallow internally
    });

    expect(captured!.devices.list).toEqual(after);
    expect(captured!.devices.isOpen).toBe(true);
    expect(window.localStorage.getItem('clouder.last_device_id')).toBeNull();
  });

  it('on 5xx — keeps picker open, no auto-refresh, no last_device write', async () => {
    const devices = [
      { id: 'cloder', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'speaker', name: 'KitchenSpeaker', type: 'Speaker' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    const refresh = vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue(devices);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockRejectedValue(new Error('spotify_api_503'));

    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.devices.refresh();
    });
    refresh.mockClear();
    act(() => { captured!.devices.open(null); });

    await act(async () => {
      await captured!.devices.pick('speaker').catch(() => {});
    });

    expect(refresh).not.toHaveBeenCalled();
    expect(captured!.devices.isOpen).toBe(true);
    expect(window.localStorage.getItem('clouder.last_device_id')).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/PlaybackProvider.devices.test.tsx`
Expected: FAIL — three new cases red because `pick` is still a stub.

- [ ] **Step 3: Implement `pick()`**

Replace the stub `pickDevice` in `PlaybackProvider.tsx`:

```ts
const pickDevice = useCallback(async (deviceId: string): Promise<void> => {
  try {
    await spotifyApi.transferMyPlayback({ deviceId, play: false }, { onAuthExpired });
    setActive(deviceId);
    lastDeviceStore.set(deviceId);
    setPickerOpen(false);
  } catch (err) {
    const message = err instanceof Error ? err.message : '';
    if (message.includes('spotify_api_404')) {
      // Device went offline between poll and tap. Refresh and keep picker open.
      void refreshDevices();
    }
    // 5xx: surface via toast in caller (UI layer); leave picker open.
    throw err;
  }
}, [onAuthExpired, refreshDevices, setActive]);
```

Add the import at the top:

```ts
import { lastDeviceStore } from './lib/lastDeviceStore';
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/PlaybackProvider.devices.test.tsx`
Expected: PASS — three new cases green; previous cases still green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/playback/PlaybackProvider.tsx frontend/src/features/playback/__tests__/PlaybackProvider.devices.test.tsx
```

---

## Task 8: Bootstrap silent restore (extends SDK ready handler)

**Files:**
- Modify: `frontend/src/features/playback/PlaybackProvider.tsx`
- Test: extend `PlaybackProvider.devices.test.tsx`.

This task changes F6's silent auto-pick of CLOUDER tab into a bootstrap that resolves `lastDeviceStore.get()` against the first `getMyDevices` poll. **F7-2:** the bootstrap transfer must NOT call `lastDeviceStore.set` (only user-driven `pick()` does).

- [ ] **Step 1: Write the failing tests**

Append three bootstrap cases to `PlaybackProvider.devices.test.tsx`. The existing F6 SDK stub mocks `Spotify.Player`. Reuse it; here is a self-contained pattern:

```tsx
// helper: install a fake SDK that fires `ready` synchronously on connect()
function installFakeSdk(deviceId: string) {
  let readyCb: ((p: { device_id: string }) => void) | null = null;
  const player = {
    addListener: vi.fn((event: string, cb: any) => {
      if (event === 'ready') readyCb = cb;
    }),
    connect: vi.fn(async () => {
      readyCb?.({ device_id: deviceId });
      return true;
    }),
    activateElement: vi.fn(async () => {}),
    pause: vi.fn(async () => {}),
    togglePlay: vi.fn(async () => {}),
    seek: vi.fn(async () => {}),
  };
  (window as any).Spotify = { Player: vi.fn(() => player) };
  return player;
}

describe('PlaybackProvider bootstrap silent restore', () => {
  beforeEach(() => {
    spotifyTokenStore.set('tok');
  });
  afterEach(() => {
    spotifyTokenStore.clear();
    window.localStorage.clear();
    vi.restoreAllMocks();
    delete (window as any).Spotify;
  });

  it('no last_device — falls back to CLOUDER tab', async () => {
    installFakeSdk('cloder-id');
    const list = [
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue(list);
    const transfer = vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    // Trigger ensureSdk by calling controls.play()-equivalent: simplest is
    // to import sdkLoader stub or just await the provider's bootstrap effect
    // (the test rig may need a hook). For Task 8 the simplest path is to
    // invoke `controls.togglePlayPause` which calls ensureSdk.
    await act(async () => {
      await captured!.controls.togglePlayPause();
    });
    await waitFor(() => expect(transfer).toHaveBeenCalled());
    expect(transfer).toHaveBeenCalledWith({ deviceId: 'cloder-id', play: false }, expect.any(Object));
    expect(window.localStorage.getItem('clouder.last_device_id')).toBeNull();
    expect(captured!.devices.cloderTabId).toBe('cloder-id');
  });

  it('last_device matches list element — restores to that device', async () => {
    installFakeSdk('cloder-id');
    window.localStorage.setItem('clouder.last_device_id', 'speaker-id');
    const list = [
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'speaker-id', name: 'Kitchen', type: 'Speaker' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue(list);
    const transfer = vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.controls.togglePlayPause();
    });
    await waitFor(() => expect(transfer).toHaveBeenCalled());
    expect(transfer).toHaveBeenCalledWith({ deviceId: 'speaker-id', play: false }, expect.any(Object));
    // F7-2: bootstrap must NOT touch localStorage
    expect(window.localStorage.getItem('clouder.last_device_id')).toBe('speaker-id'); // unchanged
  });

  it('last_device offline — falls back to CLOUDER tab', async () => {
    installFakeSdk('cloder-id');
    window.localStorage.setItem('clouder.last_device_id', 'iphone-id');
    const list = [
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      // iphone-id NOT in list
    ];
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue(list);
    const transfer = vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.controls.togglePlayPause();
    });
    await waitFor(() => expect(transfer).toHaveBeenCalled());
    expect(transfer).toHaveBeenCalledWith({ deviceId: 'cloder-id', play: false }, expect.any(Object));
    // localStorage left untouched (do NOT clear stale id — phone may come back)
    expect(window.localStorage.getItem('clouder.last_device_id')).toBe('iphone-id');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/PlaybackProvider.devices.test.tsx`
Expected: FAIL — bootstrap currently transfers to CLOUDER tab unconditionally on SDK `ready` (F6 behaviour).

- [ ] **Step 3: Refactor SDK `ready` handler**

In `PlaybackProvider.tsx`, replace the `'ready'` listener body inside `ensureSdk`:

```ts
player.addListener('ready', ({ device_id }: { device_id: string }) => {
  cloderTabIdRef.current = device_id;
  setCloderTabId(device_id);
  setSdkReady(true);
  // Bootstrap restore: refresh devices, then transfer to last_device if
  // online, else to CLOUDER tab. Resolves deviceReadyRef AFTER the
  // transfer completes so play() callers wait for the right device.
  void (async () => {
    try {
      const list = await spotifyApi.getMyDevices({ onAuthExpired });
      setDevicesList(list);
      setDevicesError(null);
      const last = lastDeviceStore.get();
      const targetId = last && list.some((d) => d.id === last) ? last : device_id;
      await spotifyApi.transferMyPlayback({ deviceId: targetId, play: false }, { onAuthExpired });
      setActive(targetId);
    } catch {
      // Network blip on first poll: fall back silently to CLOUDER tab.
      try {
        await spotifyApi.transferMyPlayback({ deviceId: device_id, play: false }, { onAuthExpired });
      } catch {
        // ignore — sdk listener will surface SDK-level errors via state events.
      }
      setActive(device_id);
    } finally {
      deviceReadyRef.current?.resolve();
    }
  })();
});
```

**Rename `deviceIdRef` → `activeDeviceIdRef` everywhere it's used in this file.** The provider previously held the local SDK device under `deviceIdRef` and treated it as "the device to play to". F7 splits them: `activeDeviceIdRef` is what `play()`/`advance()`/`seekMs` target; `cloderTabIdRef` is the local SDK ID retained for bootstrap fallback. Concrete edits inside the existing methods (e.g. `play`, `advance`):

- `const deviceId = deviceIdRef.current;` → `const deviceId = activeDeviceIdRef.current;`
- `if (!deviceIdRef.current && deviceReadyRef.current)` → `if (!activeDeviceIdRef.current && deviceReadyRef.current)`
- Remove the old `const deviceIdRef = useRef<string | null>(null);` line; only `activeDeviceIdRef` (already added in Task 5) remains.

- [ ] **Step 4: Run tests**

Run:

```
cd frontend && pnpm vitest run src/features/playback
```

Expected: every existing F6 PlaybackProvider test still green AND the three new bootstrap cases pass.

- [ ] **Step 5: Run full typecheck**

Run: `cd frontend && pnpm typecheck`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/playback/PlaybackProvider.tsx frontend/src/features/playback/__tests__/PlaybackProvider.devices.test.tsx
```

---

## Task 9: Polling effect (5s open / 30s closed)

**Files:**
- Modify: `frontend/src/features/playback/PlaybackProvider.tsx`
- Test: extend `PlaybackProvider.devices.test.tsx`.

- [ ] **Step 1: Write the failing test**

Append to `PlaybackProvider.devices.test.tsx`:

```tsx
describe('PlaybackProvider polling cadence', () => {
  beforeEach(() => {
    spotifyTokenStore.set('tok');
    vi.useFakeTimers();
  });
  afterEach(() => {
    spotifyTokenStore.clear();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('runs every 30s when picker closed, every 5s when open', async () => {
    installFakeSdk('cloder-id');
    const spy = vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.controls.togglePlayPause();   // bootstrap getMyDevices: 1 call
    });
    await vi.waitFor(() => expect(spy).toHaveBeenCalledTimes(1));

    // Picker closed: advance 30s -> +1 call
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(spy).toHaveBeenCalledTimes(2);

    // Open picker: 5s cadence
    act(() => { captured!.devices.open(null); });
    await act(async () => { vi.advanceTimersByTime(5_000); });
    expect(spy).toHaveBeenCalledTimes(3);
    await act(async () => { vi.advanceTimersByTime(5_000); });
    expect(spy).toHaveBeenCalledTimes(4);

    // Close picker: back to 30s
    act(() => { captured!.devices.close(); });
    await act(async () => { vi.advanceTimersByTime(5_000); });
    expect(spy).toHaveBeenCalledTimes(4); // no new call
    await act(async () => { vi.advanceTimersByTime(25_000); });
    expect(spy).toHaveBeenCalledTimes(5);
  });

  it('focus event fires refresh', async () => {
    installFakeSdk('cloder-id');
    const spy = vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    let captured: ReturnType<typeof usePlayback> | null = null;
    render(wrap(<Probe onValue={(v) => { captured = v; }} />));
    await act(async () => {
      await captured!.controls.togglePlayPause();
    });
    await vi.waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    await act(async () => { window.dispatchEvent(new Event('focus')); });
    expect(spy).toHaveBeenCalledTimes(2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/PlaybackProvider.devices.test.tsx`
Expected: FAIL — no polling effect yet.

- [ ] **Step 3: Add polling effect**

In `PlaybackProvider.tsx`, after the existing `useEffect(() => { advanceRef.current = advance; }, [advance])`, add:

```ts
// F7 polling: 30s closed, 5s open. Paused while sdk.ready === false.
import { usePolling } from './lib/usePolling';
// ...
usePolling(refreshDevices, {
  enabled: sdkReady,
  intervalMs: pickerOpen ? 5000 : 30000,
});
```

(The `import` line already goes at the top of the file with the other imports.)

- [ ] **Step 4: Run tests**

Run: `cd frontend && pnpm vitest run src/features/playback`
Expected: PASS — all polling cadence cases green; existing tests still green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/playback/PlaybackProvider.tsx frontend/src/features/playback/__tests__/PlaybackProvider.devices.test.tsx
```

---

## Task 10: DeviceRow component

**Files:**
- Create: `frontend/src/features/playback/DeviceRow.tsx`
- Create: `frontend/src/features/playback/DevicePicker.module.css`
- Test: `frontend/src/features/playback/__tests__/DeviceRow.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/playback/__tests__/DeviceRow.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../test/theme';
import { DeviceRow } from '../DeviceRow';
import type { SpotifyDevice } from '../lib/deviceTypes';

const wrap = (children: React.ReactNode) => (
  <MantineProvider theme={testTheme}>{children}</MantineProvider>
);

const dev = (over: Partial<SpotifyDevice> = {}): SpotifyDevice => ({
  id: 'd1',
  name: 'Device',
  type: 'Computer',
  is_active: false,
  is_private_session: false,
  is_restricted: false,
  volume_percent: null,
  ...over,
});

describe('DeviceRow', () => {
  it('renders icon, name, calls onPick on click', async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    render(wrap(<DeviceRow device={dev({ name: 'Laptop' })} cloderTabId={null} isActive={false} onPick={onPick} />));
    expect(screen.getByText('Laptop')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Laptop/ }));
    expect(onPick).toHaveBeenCalledWith('d1');
  });

  it('renders active check when isActive=true', () => {
    render(wrap(<DeviceRow device={dev()} cloderTabId={null} isActive={true} onPick={() => {}} />));
    expect(screen.getByLabelText(/active/i)).toBeInTheDocument();
  });

  it('renders restricted badge when device.is_restricted=true', () => {
    render(wrap(<DeviceRow device={dev({ is_restricted: true })} cloderTabId={null} isActive={false} onPick={() => {}} />));
    expect(screen.getByText(/restricted/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/DeviceRow.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Create CSS module + component**

```css
/* frontend/src/features/playback/DevicePicker.module.css */
.row {
  display: flex;
  align-items: center;
  gap: var(--mantine-spacing-sm);
  width: 100%;
  padding: var(--mantine-spacing-sm) var(--mantine-spacing-md);
  background: transparent;
  border: 0;
  cursor: pointer;
  text-align: left;
}
.row:hover {
  background: var(--mantine-color-gray-1);
}
.rowActive {
  background: var(--mantine-color-gray-1);
}
.indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--color-bg-elevated, var(--mantine-color-gray-0));
  border: 1px solid var(--color-border, var(--mantine-color-gray-3));
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 12px;
  cursor: pointer;
  max-width: 160px;
}
.indicator span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.indicatorCompact {
  max-width: 80px;
  padding: 2px 6px;
}
```

```tsx
// frontend/src/features/playback/DeviceRow.tsx
import { Badge, Group, Text } from '@mantine/core';
import { IconCheck } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import classes from './DevicePicker.module.css';
import { iconForDeviceType, type SpotifyDevice } from './lib/deviceTypes';

export interface DeviceRowProps {
  device: SpotifyDevice;
  cloderTabId: string | null;
  isActive: boolean;
  onPick: (deviceId: string) => void;
}

export function DeviceRow({ device, cloderTabId, isActive, onPick }: DeviceRowProps) {
  const { t } = useTranslation();
  const Icon = iconForDeviceType(device, cloderTabId);
  return (
    <button
      type="button"
      className={`${classes.row} ${isActive ? classes.rowActive : ''}`}
      onClick={() => onPick(device.id)}
      aria-label={device.name}
    >
      <Icon size={18} aria-hidden />
      <Text size="sm" flex={1} truncate>
        {device.name}
      </Text>
      {device.is_restricted ? (
        <Badge size="xs" variant="light" color="gray">
          {t('playback.devices.restricted')}
        </Badge>
      ) : null}
      {isActive ? (
        <IconCheck size={16} aria-label={t('playback.devices.active_aria')} />
      ) : null}
    </button>
  );
}
```

- [ ] **Step 4: Add i18n keys**

Edit `frontend/src/i18n/en.json`. Inside `"playback"`, add a `"devices"` block (or append to existing one):

```json
"devices": {
  "title": "Playback devices",
  "active_aria": "Active device",
  "restricted": "Restricted",
  "empty_title": "No devices found",
  "empty_body": "Open Spotify on a device, then refresh.",
  "refresh": "Refresh",
  "retry": "Retry",
  "auth_error": "Re-sign in to Spotify",
  "connecting": "Connecting to Spotify…",
  "no_device": "No device",
  "indicator_aria": "Switch playback device. Currently: {{name}}"
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/DeviceRow.test.tsx`
Expected: PASS — three cases green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/playback/DeviceRow.tsx frontend/src/features/playback/DevicePicker.module.css frontend/src/features/playback/__tests__/DeviceRow.test.tsx frontend/src/i18n/en.json
```

---

## Task 11: DeviceList component (state switch)

**Files:**
- Create: `frontend/src/features/playback/DeviceList.tsx`
- Test: `frontend/src/features/playback/__tests__/DeviceList.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/playback/__tests__/DeviceList.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../test/theme';
import { DeviceList } from '../DeviceList';
import type { SpotifyDevice } from '../lib/deviceTypes';

const wrap = (children: React.ReactNode) => (
  <MantineProvider theme={testTheme}>{children}</MantineProvider>
);

const baseProps = {
  devices: [] as readonly SpotifyDevice[],
  active: null as SpotifyDevice | null,
  cloderTabId: null as string | null,
  isLoading: false,
  error: null as 'network' | 'auth' | null,
  sdkReady: true,
  onPick: vi.fn(),
  onRefresh: vi.fn(),
};

describe('DeviceList', () => {
  it('renders connecting skeleton when sdkReady=false', () => {
    render(wrap(<DeviceList {...baseProps} sdkReady={false} />));
    expect(screen.getByText(/Connecting/i)).toBeInTheDocument();
  });

  it('renders loading skeleton when isLoading + empty list', () => {
    render(wrap(<DeviceList {...baseProps} isLoading={true} />));
    expect(screen.getByTestId('device-list-loading')).toBeInTheDocument();
  });

  it('renders empty state when ready, not loading, list empty, no error', () => {
    render(wrap(<DeviceList {...baseProps} />));
    expect(screen.getByText(/No devices found/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Refresh/i })).toBeInTheDocument();
  });

  it('renders network error with retry', async () => {
    const onRefresh = vi.fn();
    const user = userEvent.setup();
    render(wrap(<DeviceList {...baseProps} error="network" onRefresh={onRefresh} />));
    await user.click(screen.getByRole('button', { name: /Retry/i }));
    expect(onRefresh).toHaveBeenCalled();
  });

  it('renders auth error', () => {
    render(wrap(<DeviceList {...baseProps} error="auth" />));
    expect(screen.getByText(/Re-sign in/i)).toBeInTheDocument();
  });

  it('renders rows when list non-empty', () => {
    const devices: SpotifyDevice[] = [
      { id: 'd1', name: 'Laptop', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'd2', name: 'Phone', type: 'Smartphone', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    render(wrap(<DeviceList {...baseProps} devices={devices} active={devices[0]!} />));
    expect(screen.getByRole('button', { name: 'Laptop' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Phone' })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/DeviceList.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement DeviceList**

```tsx
// frontend/src/features/playback/DeviceList.tsx
import { Anchor, Button, Skeleton, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { DeviceRow } from './DeviceRow';
import type { SpotifyDevice } from './lib/deviceTypes';

export interface DeviceListProps {
  devices: readonly SpotifyDevice[];
  active: SpotifyDevice | null;
  cloderTabId: string | null;
  isLoading: boolean;
  error: 'network' | 'auth' | null;
  sdkReady: boolean;
  onPick: (deviceId: string) => void;
  onRefresh: () => void;
}

export function DeviceList(props: DeviceListProps) {
  const { devices, active, cloderTabId, isLoading, error, sdkReady, onPick, onRefresh } = props;
  const { t } = useTranslation();

  if (!sdkReady) {
    return (
      <Stack gap="xs" p="md" data-testid="device-list-connecting">
        <Skeleton height={36} />
        <Skeleton height={36} />
        <Skeleton height={36} />
        <Text size="sm" c="dimmed" ta="center">
          {t('playback.devices.connecting')}
        </Text>
      </Stack>
    );
  }

  if (isLoading && devices.length === 0) {
    return (
      <Stack gap="xs" p="md" data-testid="device-list-loading">
        <Skeleton height={36} />
        <Skeleton height={36} />
        <Skeleton height={36} />
      </Stack>
    );
  }

  if (error === 'auth') {
    return (
      <Stack gap="xs" p="md" align="center">
        <Text size="sm">{t('playback.devices.auth_error')}</Text>
        <Anchor href="/auth/login">{t('playback.devices.auth_error')}</Anchor>
      </Stack>
    );
  }

  if (error === 'network') {
    return (
      <Stack gap="xs" p="md" align="center">
        <Text size="sm" c="var(--color-danger)">
          {t('playback.devices.empty_title')}
        </Text>
        <Button size="xs" variant="light" onClick={onRefresh}>
          {t('playback.devices.retry')}
        </Button>
      </Stack>
    );
  }

  if (devices.length === 0) {
    return (
      <Stack gap="xs" p="md" align="center">
        <Text size="sm" fw={600}>
          {t('playback.devices.empty_title')}
        </Text>
        <Text size="sm" c="dimmed" ta="center">
          {t('playback.devices.empty_body')}
        </Text>
        <Button size="xs" variant="light" onClick={onRefresh}>
          {t('playback.devices.refresh')}
        </Button>
      </Stack>
    );
  }

  return (
    <Stack gap={0} py="xs">
      {devices.map((d) => (
        <DeviceRow
          key={d.id}
          device={d}
          cloderTabId={cloderTabId}
          isActive={active?.id === d.id}
          onPick={onPick}
        />
      ))}
    </Stack>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/DeviceList.test.tsx`
Expected: PASS — six cases green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/playback/DeviceList.tsx frontend/src/features/playback/__tests__/DeviceList.test.tsx
```

---

## Task 12: DevicePickerSurface (Drawer mobile / Popover desktop)

**Files:**
- Create: `frontend/src/features/playback/DevicePicker.tsx`
- Create: `frontend/src/features/playback/DeviceDrawer.tsx`
- Create: `frontend/src/features/playback/DevicePickerSurface.tsx`
- Test: `frontend/src/features/playback/__tests__/DevicePickerSurface.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/playback/__tests__/DevicePickerSurface.test.tsx
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import { testTheme } from '../../../test/theme';
import { DevicePickerSurface } from '../DevicePickerSurface';
import { PlaybackProvider } from '../PlaybackProvider';
import { AuthProvider } from '../../../auth/AuthProvider';
import { spotifyApi } from '../api/spotifyWebApi';
import { spotifyTokenStore } from '../../../auth/spotifyTokenStore';
import { usePlayback } from '../usePlayback';

function Trigger() {
  const { devices } = usePlayback();
  return <button onClick={() => devices.open(null)}>open</button>;
}

const wrapDesktop = (children: React.ReactNode) => (
  <MantineProvider theme={testTheme}>
    <MemoryRouter>
      <AuthProvider>
        <PlaybackProvider>
          {children}
          <DevicePickerSurface />
        </PlaybackProvider>
      </AuthProvider>
    </MemoryRouter>
  </MantineProvider>
);

beforeEach(() => {
  spotifyTokenStore.set('tok');
  vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
    { id: 'd1', name: 'Laptop', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
  ]);
  // Force desktop breakpoint
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn((q: string) => ({
      matches: q.includes('min-width'),
      media: q,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});
afterEach(() => {
  spotifyTokenStore.clear();
  vi.restoreAllMocks();
});

describe('DevicePickerSurface', () => {
  it('renders Popover content when desktop and open', async () => {
    const user = userEvent.setup();
    render(wrapDesktop(<Trigger />));
    await user.click(screen.getByText('open'));
    // Popover content includes the device row
    expect(await screen.findByRole('button', { name: 'Laptop' })).toBeInTheDocument();
  });

  it('renders Drawer when mobile (max-width:64em matches)', async () => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn((q: string) => ({
        matches: q.includes('max-width'),
        media: q,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
    const user = userEvent.setup();
    render(wrapDesktop(<Trigger />));
    await user.click(screen.getByText('open'));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Laptop' })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/DevicePickerSurface.test.tsx`
Expected: FAIL — surface modules not found.

- [ ] **Step 3: Create the three components**

```tsx
// frontend/src/features/playback/DevicePicker.tsx
import { Popover } from '@mantine/core';
import type { ReactNode } from 'react';

export interface DevicePickerProps {
  opened: boolean;
  anchor: HTMLElement | null;
  onClose: () => void;
  children: ReactNode;
}

export function DevicePicker({ opened, anchor, onClose, children }: DevicePickerProps) {
  return (
    <Popover
      opened={opened}
      onChange={(o) => { if (!o) onClose(); }}
      position="bottom-end"
      offset={6}
      shadow="md"
      width={280}
      withinPortal
      anchorRef={anchor ?? undefined}
    >
      {/* Anchor target is provided by the calling component via ref; we
          render only the dropdown when there's no explicit target. */}
      <Popover.Target>
        <span style={{ position: 'absolute' }} aria-hidden />
      </Popover.Target>
      <Popover.Dropdown p={0}>{children}</Popover.Dropdown>
    </Popover>
  );
}
```

```tsx
// frontend/src/features/playback/DeviceDrawer.tsx
import { Drawer } from '@mantine/core';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

export interface DeviceDrawerProps {
  opened: boolean;
  onClose: () => void;
  children: ReactNode;
}

export function DeviceDrawer({ opened, onClose, children }: DeviceDrawerProps) {
  const { t } = useTranslation();
  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="bottom"
      title={t('playback.devices.title')}
      size="auto"
      lockScroll
    >
      {children}
    </Drawer>
  );
}
```

```tsx
// frontend/src/features/playback/DevicePickerSurface.tsx
import { useMediaQuery } from '@mantine/hooks';
import { useMantineTheme } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { DeviceList } from './DeviceList';
import { DevicePicker } from './DevicePicker';
import { DeviceDrawer } from './DeviceDrawer';
import { usePlayback } from './usePlayback';

export function DevicePickerSurface() {
  const { t } = useTranslation();
  const theme = useMantineTheme();
  const isMobile = useMediaQuery(`(max-width: ${theme.breakpoints.md})`);
  const { sdk, devices } = usePlayback();

  const onPick = async (deviceId: string) => {
    try {
      await devices.pick(deviceId);
    } catch (err) {
      const message = err instanceof Error ? err.message : '';
      const is404 = message.includes('spotify_api_404');
      notifications.show({
        color: 'red',
        message: is404
          ? t('playback.toasts.device_offline')
          : t('playback.toasts.device_switch_failed'),
      });
    }
  };

  const list = (
    <DeviceList
      devices={devices.list}
      active={devices.active}
      cloderTabId={devices.cloderTabId}
      isLoading={devices.isLoading}
      error={devices.error}
      sdkReady={sdk.ready}
      onPick={onPick}
      onRefresh={() => void devices.refresh()}
    />
  );

  if (isMobile) {
    return (
      <DeviceDrawer opened={devices.isOpen} onClose={devices.close}>
        {list}
      </DeviceDrawer>
    );
  }
  return (
    <DevicePicker opened={devices.isOpen} anchor={devices.pickerAnchor} onClose={devices.close}>
      {list}
    </DevicePicker>
  );
}
```

- [ ] **Step 4: Add the missing toast i18n keys**

In `frontend/src/i18n/en.json` under `playback.toasts`, ensure both keys exist (already has `device_offline`):

```json
"toasts": {
  ...,
  "device_offline": "Device went offline",
  "device_switch_failed": "Couldn't switch device"
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/DevicePickerSurface.test.tsx`
Expected: PASS — both cases green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/playback/DevicePicker.tsx frontend/src/features/playback/DeviceDrawer.tsx frontend/src/features/playback/DevicePickerSurface.tsx frontend/src/features/playback/__tests__/DevicePickerSurface.test.tsx frontend/src/i18n/en.json
```

---

## Task 13: DeviceIndicator pill

**Files:**
- Create: `frontend/src/features/playback/DeviceIndicator.tsx`
- Test: `frontend/src/features/playback/__tests__/DeviceIndicator.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/playback/__tests__/DeviceIndicator.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../test/theme';
import { DeviceIndicator } from '../DeviceIndicator';
import type { SpotifyDevice } from '../lib/deviceTypes';

const wrap = (children: React.ReactNode) => (
  <MantineProvider theme={testTheme}>{children}</MantineProvider>
);

const dev: SpotifyDevice = {
  id: 'd1',
  name: 'KitchenSpeaker',
  type: 'Speaker',
  is_active: true,
  is_private_session: false,
  is_restricted: false,
  volume_percent: 60,
};

describe('DeviceIndicator', () => {
  it('renders icon and name in full mode', () => {
    render(wrap(<DeviceIndicator mode="full" active={dev} cloderTabId={null} onOpen={() => {}} />));
    expect(screen.getByText('KitchenSpeaker')).toBeInTheDocument();
  });

  it('renders compact mode without chevron', () => {
    render(wrap(<DeviceIndicator mode="compact" active={dev} cloderTabId={null} onOpen={() => {}} />));
    expect(screen.queryByLabelText(/chevron/i)).toBeNull();
  });

  it('calls onOpen with the button element when clicked', async () => {
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(wrap(<DeviceIndicator mode="full" active={dev} cloderTabId={null} onOpen={onOpen} />));
    await user.click(screen.getByRole('button'));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0]![0]).toBeInstanceOf(HTMLElement);
  });

  it('shows "No device" when active is null', () => {
    render(wrap(<DeviceIndicator mode="full" active={null} cloderTabId={null} onOpen={() => {}} />));
    expect(screen.getByText(/No device/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/DeviceIndicator.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement DeviceIndicator**

```tsx
// frontend/src/features/playback/DeviceIndicator.tsx
import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { IconChevronDown } from '@tabler/icons-react';
import classes from './DevicePicker.module.css';
import { iconForDeviceType, type SpotifyDevice } from './lib/deviceTypes';

export interface DeviceIndicatorProps {
  mode: 'full' | 'compact';
  active: SpotifyDevice | null;
  cloderTabId: string | null;
  onOpen: (anchor: HTMLElement) => void;
}

export function DeviceIndicator({ mode, active, cloderTabId, onOpen }: DeviceIndicatorProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLButtonElement | null>(null);
  const Icon = active ? iconForDeviceType(active, cloderTabId) : null;
  const name = active?.name ?? t('playback.devices.no_device');
  const ariaLabel = t('playback.devices.indicator_aria', { name });
  return (
    <button
      ref={ref}
      type="button"
      className={`${classes.indicator} ${mode === 'compact' ? classes.indicatorCompact : ''}`}
      onClick={() => ref.current && onOpen(ref.current)}
      aria-label={ariaLabel}
    >
      {Icon ? <Icon size={mode === 'compact' ? 14 : 14} aria-hidden /> : null}
      <span>{name}</span>
      {mode === 'full' ? <IconChevronDown size={12} aria-hidden /> : null}
    </button>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/DeviceIndicator.test.tsx`
Expected: PASS — four cases green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/playback/DeviceIndicator.tsx frontend/src/features/playback/__tests__/DeviceIndicator.test.tsx
```

---

## Task 14: Wire DevicePickerSurface into _layout PlaybackChrome

**Files:**
- Modify: `frontend/src/routes/_layout.tsx`

- [ ] **Step 1: Read the current PlaybackChrome**

Open `frontend/src/routes/_layout.tsx` and locate the `PlaybackChrome` function (around line 124). Note current children: `<MiniBar ... />` and `<LeaveContextDialog ... />`.

- [ ] **Step 2: Add DevicePickerSurface mount**

Add the import near the top of the file:

```ts
import { DevicePickerSurface } from '../features/playback/DevicePickerSurface';
```

Add the component at the end of `PlaybackChrome`'s return:

```tsx
return (
  <>
    {showMiniBar && (
      <MiniBar
        ...existing props...
      />
    )}
    <LeaveContextDialog ...existing props... />
    <DevicePickerSurface />   {/* NEW */}
  </>
);
```

- [ ] **Step 3: Run all tests**

Run: `cd frontend && pnpm vitest run`
Expected: typecheck clean, all existing tests still green.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/_layout.tsx
```

---

## Task 15: Add DeviceIndicator to PlayerCard subline + wire onOpenDevicePicker through usePlayback

**Files:**
- Modify: `frontend/src/features/playback/PlayerCard.tsx`
- Modify: `frontend/src/features/playback/__tests__/PlayerCard.test.tsx` (existing) — update onOpenDevicePicker mock pattern.

The PlayerCard already accepts `onOpenDevicePicker`. F7 keeps the prop (CurateSession passes it down) but additionally renders a `DeviceIndicator` in the subline. The indicator's `onOpen` callback is what consumers invoke; consumers' `onOpenDevicePicker` is preserved for the disconnected-state link.

- [ ] **Step 1: Update PlayerCard to render DeviceIndicator**

Add a new optional prop on `PlayerCardProps`:

```ts
deviceIndicator?: ReactNode;
```

Inside the `Stack` that holds title + subline + metaRow (around line 187), insert `deviceIndicator` below `subline` and above `metaRow`:

```tsx
{showText ? (
  <Stack gap={4} flex={1} miw={0}>
    <Title ...>...</Title>
    {mixName ? ... : null}
    {subline}
    {deviceIndicator}                    {/* NEW */}
    {metaRow}
  </Stack>
) : (
  <div style={{ flex: 1 }} />
)}
```

(In `mini` variant we still pass `deviceIndicator` in MiniBar separately — see Task 16. PlayerCard's mini variant is rendered only as fall-through and showText is generally true in F6 callers; leave as-is.)

- [ ] **Step 2: Update existing PlayerCard test to pass `deviceIndicator={null}`**

Open `frontend/src/features/playback/__tests__/PlayerCard.test.tsx`. Add `deviceIndicator: null` to `baseProps`. Expected: existing tests still green; no new test required here (DeviceIndicator's own tests cover its rendering).

- [ ] **Step 3: Run tests**

Run: `cd frontend && pnpm vitest run src/features/playback`
Expected: PASS — existing PlayerCard suite still green.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/playback/PlayerCard.tsx frontend/src/features/playback/__tests__/PlayerCard.test.tsx
```

---

## Task 16: Add DeviceIndicator to MiniBar

**Files:**
- Modify: `frontend/src/features/playback/MiniBar.tsx`
- Modify: `frontend/src/features/playback/__tests__/MiniBar.test.tsx` (existing) — extend.

- [ ] **Step 1: Update MiniBar**

Add a new optional prop on `MiniBarProps`:

```ts
deviceIndicator?: React.ReactNode;
```

Render it between the title/artists `Stack` and the play/pause `ActionIcon`:

```tsx
<Stack gap={2} flex={1} miw={0}>
  ...title link...
  ...artists Text...
</Stack>
{deviceIndicator}             {/* NEW */}
<ActionIcon ...play/pause... />
```

- [ ] **Step 2: Extend MiniBar test**

In the existing test file, add a case verifying the indicator slot renders when provided:

```tsx
it('renders deviceIndicator slot', () => {
  render(wrap(<MiniBar {...baseProps} deviceIndicator={<span data-testid="indicator">x</span>} />));
  expect(screen.getByTestId('indicator')).toBeInTheDocument();
});
```

- [ ] **Step 3: Run tests**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/MiniBar.test.tsx`
Expected: PASS — existing + new case green.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/playback/MiniBar.tsx frontend/src/features/playback/__tests__/MiniBar.test.tsx
```

---

## Task 17: Wire DeviceIndicator into PlaybackChrome's MiniBar + CurateSession's PlayerCard

**Files:**
- Modify: `frontend/src/routes/_layout.tsx` — PlaybackChrome MiniBar consumer.
- Modify: `frontend/src/features/curate/components/CurateSession.tsx` — PlayerCard consumer + replace placeholder `onOpenDevicePicker`.

- [ ] **Step 1: Update PlaybackChrome to pass DeviceIndicator into MiniBar**

In `_layout.tsx` `PlaybackChrome`, add the import:

```ts
import { DeviceIndicator } from '../features/playback/DeviceIndicator';
```

Inside `PlaybackChrome`, read `devices` from `usePlayback()` (already used for other fields):

```tsx
const { devices } = usePlayback();
```

Pass the indicator into MiniBar:

```tsx
<MiniBar
  ...existing props...
  deviceIndicator={
    <DeviceIndicator
      mode="compact"
      active={devices.active}
      cloderTabId={devices.cloderTabId}
      onOpen={(anchor) => devices.open(anchor)}
    />
  }
/>
```

- [ ] **Step 2: Update CurateSession's PlayerCard call site**

Open `frontend/src/features/curate/components/CurateSession.tsx`. Locate the `<PlayerCard>` JSX (~line 220). Currently `onOpenDevicePicker={() => {/* placeholder */}}`. Replace with `playback.devices.open(...)` and pass `DeviceIndicator` for full mode:

```tsx
<PlayerCard
  ...existing props...
  deviceIndicator={
    <DeviceIndicator
      mode="full"
      active={playback.devices.active}
      cloderTabId={playback.devices.cloderTabId}
      onOpen={(anchor) => playback.devices.open(anchor)}
    />
  }
  onOpenDevicePicker={() => playback.devices.open(null)}
/>
```

Add the import in CurateSession:

```ts
import { DeviceIndicator } from '../../playback/DeviceIndicator';
```

- [ ] **Step 3: Run all tests**

Run: `cd frontend && pnpm vitest run && pnpm typecheck`
Expected: typecheck clean; all existing F1–F6 suites still green.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/_layout.tsx frontend/src/features/curate/components/CurateSession.tsx
```

---

## Task 18: Integration test 1 — Cold start, no last_device

**Files:**
- Create: `frontend/src/features/playback/__tests__/integration.f7.test.tsx`

This and Tasks 19–21 group the F7 integration scenarios into one file. Use the existing F6 integration batches as the structural model.

- [ ] **Step 1: Write the test**

```tsx
// frontend/src/features/playback/__tests__/integration.f7.test.tsx
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { MemoryRouter } from 'react-router';
import { testTheme } from '../../../test/theme';
import { PlaybackProvider } from '../PlaybackProvider';
import { DevicePickerSurface } from '../DevicePickerSurface';
import { DeviceIndicator } from '../DeviceIndicator';
import { usePlayback } from '../usePlayback';
import { spotifyApi } from '../api/spotifyWebApi';
import { spotifyTokenStore } from '../../../auth/spotifyTokenStore';
import { AuthProvider } from '../../../auth/AuthProvider';

function App() {
  const { sdk, devices, controls } = usePlayback();
  return (
    <>
      <button onClick={() => controls.togglePlayPause()}>boot</button>
      <DeviceIndicator
        mode="full"
        active={devices.active}
        cloderTabId={devices.cloderTabId}
        onOpen={(a) => devices.open(a)}
      />
      <DevicePickerSurface />
      <span data-testid="active">{devices.active?.name ?? 'none'}</span>
      <span data-testid="ready">{String(sdk.ready)}</span>
    </>
  );
}

const wrap = (ui: React.ReactNode) => (
  <MantineProvider theme={testTheme}>
    <Notifications />
    <MemoryRouter>
      <AuthProvider>
        <PlaybackProvider>{ui}</PlaybackProvider>
      </AuthProvider>
    </MemoryRouter>
  </MantineProvider>
);

function installFakeSdk(deviceId: string) {
  let readyCb: ((p: { device_id: string }) => void) | null = null;
  const player = {
    addListener: vi.fn((event: string, cb: any) => {
      if (event === 'ready') readyCb = cb;
    }),
    connect: vi.fn(async () => {
      readyCb?.({ device_id: deviceId });
      return true;
    }),
    activateElement: vi.fn(async () => {}),
    pause: vi.fn(async () => {}),
    togglePlay: vi.fn(async () => {}),
    seek: vi.fn(async () => {}),
  };
  (window as any).Spotify = { Player: vi.fn(() => player) };
  // also stub loadSpotifySdk to resolve immediately
  return player;
}

beforeEach(() => {
  spotifyTokenStore.set('tok');
});
afterEach(() => {
  spotifyTokenStore.clear();
  window.localStorage.clear();
  vi.restoreAllMocks();
  delete (window as any).Spotify;
});

describe('F7 integration · cold start', () => {
  it('no last_device — falls back to CLOUDER tab; indicator shows CLOUDER', async () => {
    installFakeSdk('cloder-id');
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER Web Player', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    const transfer = vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    const user = userEvent.setup();
    render(wrap(<App />));
    await user.click(screen.getByText('boot'));
    await waitFor(() => expect(transfer).toHaveBeenCalled());
    expect(transfer).toHaveBeenCalledWith({ deviceId: 'cloder-id', play: false }, expect.any(Object));
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('CLOUDER Web Player'));
    expect(window.localStorage.getItem('clouder.last_device_id')).toBeNull();
  });
});
```

- [ ] **Step 2: Run test**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/integration.f7.test.tsx`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/playback/__tests__/integration.f7.test.tsx
```

---

## Task 19: Integration tests 2-5 — restore + offline + open picker

Append these scenarios to `integration.f7.test.tsx` in the same `describe` (or a new one).

- [ ] **Step 1: Add `restore-online`, `restore-offline`, `open-picker-desktop`, `open-picker-mobile` cases**

Append:

```tsx
describe('F7 integration · restore + open', () => {
  it('last_device online — silent restore to that device', async () => {
    installFakeSdk('cloder-id');
    window.localStorage.setItem('clouder.last_device_id', 'iphone');
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'iphone', name: 'iPhone', type: 'Smartphone', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    const transfer = vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    const user = userEvent.setup();
    render(wrap(<App />));
    await user.click(screen.getByText('boot'));
    await waitFor(() => expect(transfer).toHaveBeenCalledWith({ deviceId: 'iphone', play: false }, expect.any(Object)));
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('iPhone'));
    expect(window.localStorage.getItem('clouder.last_device_id')).toBe('iphone'); // unchanged
  });

  it('last_device offline — fallback CLOUDER; localStorage retained', async () => {
    installFakeSdk('cloder-id');
    window.localStorage.setItem('clouder.last_device_id', 'iphone');
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    const transfer = vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    const user = userEvent.setup();
    render(wrap(<App />));
    await user.click(screen.getByText('boot'));
    await waitFor(() => expect(transfer).toHaveBeenCalledWith({ deviceId: 'cloder-id', play: false }, expect.any(Object)));
    expect(window.localStorage.getItem('clouder.last_device_id')).toBe('iphone'); // unchanged
  });

  it('open picker desktop renders Popover with list', async () => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn((q: string) => ({
        matches: q.includes('min-width'), media: q, onchange: null,
        addListener: vi.fn(), removeListener: vi.fn(),
        addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
      })),
    });
    installFakeSdk('cloder-id');
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    const user = userEvent.setup();
    render(wrap(<App />));
    await user.click(screen.getByText('boot'));
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('CLOUDER'));
    await user.click(screen.getByRole('button', { name: /Switch playback device/i }));
    expect(await screen.findByRole('button', { name: 'CLOUDER' })).toBeInTheDocument();
  });

  it('open picker mobile renders Drawer dialog with list', async () => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn((q: string) => ({
        matches: q.includes('max-width'), media: q, onchange: null,
        addListener: vi.fn(), removeListener: vi.fn(),
        addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
      })),
    });
    installFakeSdk('cloder-id');
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    const user = userEvent.setup();
    render(wrap(<App />));
    await user.click(screen.getByText('boot'));
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('CLOUDER'));
    await user.click(screen.getByRole('button', { name: /Switch playback device/i }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/integration.f7.test.tsx`
Expected: PASS — five total scenarios green.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/playback/__tests__/integration.f7.test.tsx
```

---

## Task 20: Integration tests 6-9 — pick happy + 404 + disconnected + cadence

Append the remaining scenarios:

- [ ] **Step 1: Add cases**

```tsx
describe('F7 integration · pick + cadence', () => {
  it('pick remote device happy path — closes picker, persists last_device', async () => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn((q: string) => ({
        matches: q.includes('min-width'), media: q, onchange: null,
        addListener: vi.fn(), removeListener: vi.fn(),
        addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
      })),
    });
    installFakeSdk('cloder-id');
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'speaker', name: 'KitchenSpeaker', type: 'Speaker', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    const user = userEvent.setup();
    render(wrap(<App />));
    await user.click(screen.getByText('boot'));
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('CLOUDER'));
    await user.click(screen.getByRole('button', { name: /Switch playback device/i }));
    await user.click(await screen.findByRole('button', { name: 'KitchenSpeaker' }));
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('KitchenSpeaker'));
    expect(window.localStorage.getItem('clouder.last_device_id')).toBe('speaker');
  });

  it('pick 404 — toast + auto-refresh + picker stays open', async () => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn((q: string) => ({
        matches: q.includes('min-width'), media: q, onchange: null,
        addListener: vi.fn(), removeListener: vi.fn(),
        addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
      })),
    });
    installFakeSdk('cloder-id');
    const before = [
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'stale', name: 'StalePhone', type: 'Smartphone' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    const after = [before[0]!];
    vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValueOnce(before).mockResolvedValueOnce(after);
    const transfer = vi.spyOn(spotifyApi, 'transferMyPlayback')
      .mockResolvedValueOnce()                              // bootstrap
      .mockRejectedValueOnce(new Error('spotify_api_404')); // user pick
    const user = userEvent.setup();
    render(wrap(<App />));
    await user.click(screen.getByText('boot'));
    await waitFor(() => expect(transfer).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: /Switch playback device/i }));
    await user.click(await screen.findByRole('button', { name: 'StalePhone' }));
    expect(await screen.findByText(/Device went offline/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('button', { name: 'StalePhone' })).toBeNull());
  });

  it('disconnected → picker (active device leaves list)', async () => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn((q: string) => ({
        matches: q.includes('min-width'), media: q, onchange: null,
        addListener: vi.fn(), removeListener: vi.fn(),
        addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
      })),
    });
    installFakeSdk('cloder-id');
    window.localStorage.setItem('clouder.last_device_id', 'speaker');
    const before = [
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
      { id: 'speaker', name: 'KitchenSpeaker', type: 'Speaker' as const, is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ];
    const after = [before[0]!]; // speaker dropped
    const polls = vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValueOnce(before).mockResolvedValue(after);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    const user = userEvent.setup();
    render(wrap(<App />));
    await user.click(screen.getByText('boot'));
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('KitchenSpeaker'));
    // simulate next polling tick — easiest path: dispatch focus event to force refresh
    await act(async () => { window.dispatchEvent(new Event('focus')); });
    await waitFor(() => expect(polls).toHaveBeenCalledTimes(2));
    // active is now null (speaker not in list); status flipped to disconnected
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('none'));
  });

  it('polling cadence — 30s closed, 5s open', async () => {
    vi.useFakeTimers();
    installFakeSdk('cloder-id');
    const polls = vi.spyOn(spotifyApi, 'getMyDevices').mockResolvedValue([
      { id: 'cloder-id', name: 'CLOUDER', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null },
    ]);
    vi.spyOn(spotifyApi, 'transferMyPlayback').mockResolvedValue();
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn((q: string) => ({
        matches: q.includes('min-width'), media: q, onchange: null,
        addListener: vi.fn(), removeListener: vi.fn(),
        addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
      })),
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(wrap(<App />));
    await user.click(screen.getByText('boot'));
    await vi.waitFor(() => expect(polls).toHaveBeenCalledTimes(1));
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(polls).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole('button', { name: /Switch playback device/i }));
    await act(async () => { vi.advanceTimersByTime(5_000); });
    expect(polls).toHaveBeenCalledTimes(3);
    vi.useRealTimers();
  });
});
```

- [ ] **Step 2: Run tests**

Run: `cd frontend && pnpm vitest run src/features/playback/__tests__/integration.f7.test.tsx`
Expected: PASS — nine total scenarios green.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/playback/__tests__/integration.f7.test.tsx
```

---

## Task 21: Final verification — full suite + typecheck + bundle

- [ ] **Step 1: Full vitest run**

Run: `cd frontend && pnpm vitest run`
Expected: All suites green. Test count delta target: +20 to +30 vs F6 baseline (~430 / ~440 total). If count is below the floor, add another unit case for any uncovered branch in `PlaybackProvider.devices`.

- [ ] **Step 2: Typecheck**

Run: `cd frontend && pnpm typecheck`
Expected: zero errors.

- [ ] **Step 3: Lint**

Run: `cd frontend && pnpm lint`
Expected: zero errors. Common issues to watch for:
- Unused imports after the `deviceIdRef → activeDeviceIdRef` rename in Task 8.
- Hook dep warnings on the polling effect (`refreshDevices` in `usePolling` deps via `usePolling`'s ref pattern, not the effect itself).
- No `import React from 'react'` in pure JSX-runtime test files (CLAUDE.md gotcha #32).

- [ ] **Step 4: Bundle check**

Run: `cd frontend && pnpm build`
Expected: `dist/assets/index-<hash>.js` size ≤ F6 baseline + 18 KB. F6 baseline ≈ 910 KB. Hard ceiling: 928 KB.

If over budget, common culprits:
- Re-importing all of `@tabler/icons-react` instead of named imports.
- Inlining the polling helper inside `PlaybackProvider` instead of using the shared `usePolling` hook.

- [ ] **Step 5: Manual smoke (out of CI)**

If a real Spotify Premium account is available:

1. `pnpm dev` from `frontend/` (CLAUDE.md gotcha — must be run from `frontend/`, not worktree root).
2. Sign in, navigate to a Curate session, hit `Space` → audio plays through CLOUDER tab. Verify pill in PlayerCard reads "CLOUDER Web Player".
3. Open Spotify on a phone in the same account → wait ≤ 30 s → device pill in CLOUDER picker shows the phone.
4. Tap pill → picker opens. Tap phone → audio shifts to phone within ~1 s. Indicator pill updates.
5. Reload page → after SDK ready, audio resumes on phone (silent restore).
6. Disable Wi-Fi on phone → ≤ 30 s later, PlayerCard flips to disconnected state. Tap "Open device picker" link → picker shows only CLOUDER tab.

- [ ] **Step 6: Final commit if any housekeeping fixes were needed**

```bash
git status
git add -p
# message via skill
```

---

## Acceptance Criteria (from spec § 9)

- [ ] `DeviceIndicator` renders in PlayerCard subline (full mode) and MiniBar (compact mode); tap opens picker.
- [ ] Bootstrap silent restore: `last_device_id` saved + online → audio on saved device after SDK ready (no manual click).
- [ ] `lastDeviceStore.set` is called only inside user-driven `pick()` (verified by integration tests 1 + 2 + 3: no localStorage write on bootstrap auto-pick).
- [ ] Picker auto-refreshes on `transferMyPlayback` 404; offline device removed from list (integration test 7).
- [ ] Polling cadence verified: 5 s open, 30 s closed (integration test 9 + unit test 9).
- [ ] F6 disconnected-state "Open device picker" link wired and opens picker.
- [ ] Empty list state copy matches OPEN_QUESTIONS Q5: "No devices found. Open Spotify on a device, then refresh."
- [ ] All 14 unit + 9 integration tests green.
- [ ] F1–F6 test suites: zero regressions.
- [ ] Bundle increase ≤ 18 KB minified.

---

## Self-review notes

- **Spec coverage:** Every § 3 architectural decision has a task. F7-1 (active vs cloderTab refs) → Task 8 rename; F7-2 (no localStorage write on bootstrap) → Task 7 + integration tests 1/2/3; F7-3 (deviceReadyRef extension) → Task 8; F7-4 (single picker mount) → Task 14; F7-5 (single polling effect) → Task 9; F7-6 (polling enabled on all authenticated routes) → mounted in `_layout` → Task 14; F7-7 (icon mapping + CLOUDER override) → Task 1; F7-8 (auto-refresh on 404) → Task 7 + integration test 7; F7-9 (active offline → disconnected) → Task 6 + integration test 8; F7-10 (localStorage try/catch) → Task 2.
- **Placeholders:** none — every code step has full code.
- **Type consistency:** `SpotifyDevice` defined Task 1, used identically Tasks 3, 5–13. `DevicesSlice` defined Task 5, consumed Tasks 12, 13, 17. `iconForDeviceType(device, cloderTabId)` signature stable Tasks 1, 10, 13.
- **Edge case from spec § 10.1 (`pendingPickRef` for serialised picks):** not in plan tasks. Reason: a single-tap UX with picker auto-close (Task 7 happy path closes the picker on success) means the second tap can only happen after the first resolves. If sustained DJ use surfaces a real race, file as `FUTURE-F7-6` and add a `pendingPickRef` later.
