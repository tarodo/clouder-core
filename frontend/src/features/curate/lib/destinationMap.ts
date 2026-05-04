import type { TriageBucket } from '../../triage/lib/bucketLabels';

export const STAGING_HOTKEY_LIMIT = 9;

export type TechHotkeyType = 'NEW' | 'OLD' | 'NOT';

function activeStaging(buckets: TriageBucket[]): TriageBucket[] {
  return buckets.filter((b) => b.bucket_type === 'STAGING' && !b.inactive);
}

export function byPosition(buckets: TriageBucket[], position: number): TriageBucket | null {
  const active = activeStaging(buckets);
  return active[position] ?? null;
}

export function byTechType(
  buckets: TriageBucket[],
  type: TechHotkeyType,
): TriageBucket | null {
  return buckets.find((b) => b.bucket_type === type) ?? null;
}

export function byDiscard(buckets: TriageBucket[]): TriageBucket | null {
  return buckets.find((b) => b.bucket_type === 'DISCARD') ?? null;
}

export function resolveStagingHotkeys(buckets: TriageBucket[]): TriageBucket[] {
  return activeStaging(buckets).slice(0, STAGING_HOTKEY_LIMIT);
}

export function stagingOverflow(buckets: TriageBucket[]): TriageBucket[] {
  return activeStaging(buckets).slice(STAGING_HOTKEY_LIMIT);
}
