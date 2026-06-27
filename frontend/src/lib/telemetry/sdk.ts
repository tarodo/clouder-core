import { api } from '../../api/client';

export type TelemetryProps = Record<string, unknown>;

export interface TelemetryEnvelope {
  event_name: string;
  event_id: string;
  session_id: string;
  ts_client: string;
  context: {
    user_id: null;
    device: 'desktop' | 'mobile' | 'tablet';
    route: string | null;
    app_version: string;
  };
  props: TelemetryProps;
}

const FLUSH_INTERVAL_MS = 10_000;
const FLUSH_SIZE = 25;
const MAX_CHUNK_BYTES = 60_000; // headroom under the 64KB keepalive cap

const CROCKFORD = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

function ulid(): string {
  let now = Date.now();
  const time = new Array<string>(10);
  for (let i = 9; i >= 0; i--) {
    time[i] = CROCKFORD[now % 32]!;
    now = Math.floor(now / 32);
  }
  const rnd = new Uint8Array(16);
  crypto.getRandomValues(rnd);
  let r = '';
  for (let i = 0; i < 16; i++) r += CROCKFORD[(rnd[i] ?? 0) % 32]!;
  return time.join('') + r;
}

function uuidv4(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  b[6] = ((b[6] ?? 0) & 0x0f) | 0x40;
  b[8] = ((b[8] ?? 0) & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, '0'));
  return `${h[0]!}${h[1]!}${h[2]!}${h[3]!}-${h[4]!}${h[5]!}-${h[6]!}${h[7]!}-${h[8]!}${h[9]!}-${h[10]!}${h[11]!}${h[12]!}${h[13]!}${h[14]!}${h[15]!}`;
}

const APP_VERSION = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'dev';

function telemetryEnabled(): boolean {
  return import.meta.env.VITE_TELEMETRY_ENABLED === 'true';
}

function device(): 'desktop' | 'mobile' | 'tablet' {
  if (typeof window === 'undefined') return 'desktop';
  return window.innerWidth > 0 && window.innerWidth < 768 ? 'mobile' : 'desktop';
}

const SESSION_ID = uuidv4(); // fresh per tab, never persisted (§4.1)
let currentRoute: string | null = null;
let buffer: TelemetryEnvelope[] = [];
const shownAt = new Map<string, number>();
let seen = new Set<string>();
let triggersBound = false;

function bindFlushTriggers(): void {
  if (triggersBound || typeof window === 'undefined') return;
  triggersBound = true;
  setInterval(() => {
    if (buffer.length) void flush();
  }, FLUSH_INTERVAL_MS);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') void flush();
  });
  window.addEventListener('pagehide', () => void flush());
}

export function chunkEvents(
  events: TelemetryEnvelope[],
  maxBytes = MAX_CHUNK_BYTES,
): TelemetryEnvelope[][] {
  const chunks: TelemetryEnvelope[][] = [];
  let cur: TelemetryEnvelope[] = [];
  let bytes = 2; // {"events":[]} braces approximated
  for (const e of events) {
    const size = JSON.stringify(e).length + 1;
    if (cur.length && bytes + size > maxBytes) {
      chunks.push(cur);
      cur = [];
      bytes = 2;
    }
    cur.push(e);
    bytes += size;
  }
  if (cur.length) chunks.push(cur);
  return chunks;
}

export async function flush(): Promise<void> {
  if (!buffer.length) return;
  const events = buffer;
  buffer = [];
  for (const chunk of chunkEvents(events)) {
    // Fire-and-forget: failure (incl. swallowed 401) drops the batch silently (§4.2).
    void api('/v1/telemetry', {
      method: 'POST',
      keepalive: true,
      suppressAuthFailure: true,
      body: JSON.stringify({ events: chunk }),
    }).catch(() => {});
  }
}

export function debounceTrack(
  ms: number,
): (eventName: string, props?: TelemetryProps) => void {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let name = '';
  let lastProps: TelemetryProps = {};
  return (eventName, props = {}) => {
    name = eventName;
    lastProps = props;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      telemetry.track(name, lastProps);
    }, ms);
  };
}

export const telemetry = {
  track(eventName: string, props: TelemetryProps = {}): void {
    if (!telemetryEnabled()) return; // VITE_TELEMETRY_ENABLED default off → no-op
    bindFlushTriggers();
    buffer.push({
      event_name: eventName,
      event_id: ulid(),
      session_id: SESSION_ID,
      ts_client: new Date().toISOString(),
      context: { user_id: null, device: device(), route: currentRoute, app_version: APP_VERSION },
      props,
    });
    if (buffer.length >= FLUSH_SIZE) void flush();
  },
  markShown(key: string): void {
    shownAt.set(key, performance.now());
  },
  msSinceShown(key: string): number {
    const t = shownAt.get(key);
    return t == null ? 0 : Math.round(performance.now() - t);
  },
  markSeen(key: string): void {
    seen.add(key);
  },
  seenCount(): number {
    return seen.size;
  },
  resetSeen(): void {
    seen = new Set();
  },
  setRoute(route: string | null): void {
    currentRoute = route;
  },
  getSessionId(): string {
    return SESSION_ID;
  },
};

export const __ulidForTest = ulid;
