import type { TriageBlock } from '../../triage/hooks/useTriageBlock';

export const LAST_CURATE_LOCATION_KEY = 'clouder.lastCurateLocation';
export const LAST_CURATE_STYLE_KEY = 'clouder.lastCurateStyle';

export interface CurateLocation {
  blockId: string;
  bucketId: string;
  updatedAt: string;
}

type Storage = Record<string, CurateLocation>;

function readStorage(): Storage {
  let raw: string | null;
  try {
    raw = localStorage.getItem(LAST_CURATE_LOCATION_KEY);
  } catch {
    return {};
  }
  if (raw === null) return {};
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Storage;
    }
    throw new Error('invalid shape');
  } catch {
    try {
      localStorage.removeItem(LAST_CURATE_LOCATION_KEY);
    } catch {
      /* ignore */
    }
    return {};
  }
}

function writeStorage(s: Storage): void {
  try {
    localStorage.setItem(LAST_CURATE_LOCATION_KEY, JSON.stringify(s));
  } catch {
    /* private mode etc. — ignore */
  }
}

export function readLastCurateLocation(styleId: string): CurateLocation | null {
  return readStorage()[styleId] ?? null;
}

export function writeLastCurateLocation(
  styleId: string,
  blockId: string,
  bucketId: string,
): void {
  const s = readStorage();
  s[styleId] = { blockId, bucketId, updatedAt: new Date().toISOString() };
  writeStorage(s);
}

export function clearLastCurateLocation(styleId: string): void {
  const s = readStorage();
  if (styleId in s) {
    delete s[styleId];
    writeStorage(s);
  }
}

export function readLastCurateStyle(): string | null {
  try {
    return localStorage.getItem(LAST_CURATE_STYLE_KEY);
  } catch {
    return null;
  }
}

export function writeLastCurateStyle(styleId: string): void {
  try {
    localStorage.setItem(LAST_CURATE_STYLE_KEY, styleId);
  } catch {
    /* ignore */
  }
}

export function isStaleLocation(
  loc: { blockId: string; bucketId: string },
  block: TriageBlock,
): boolean {
  if (block.status === 'FINALIZED') return true;
  const bucket = block.buckets.find((b) => b.id === loc.bucketId);
  if (!bucket) return true;
  if (bucket.bucket_type === 'STAGING') return true;
  return false;
}
