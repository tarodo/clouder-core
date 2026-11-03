export function formatLength(ms: number | null): string {
  // Em-dash on null OR zero — preserves F1 legacy behavior; covered by tests.
  if (!ms) return '—';
  const total = Math.round(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

/** The local calendar date as YYYY-MM-DD: reads like the release date beside it. */
export function formatAdded(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function formatReleaseDate(iso: string | null): string {
  if (!iso) return '—';
  return iso;
}

/** A YouTube comment count: the collector reads one page, so 100 means 100 or more. */
export function formatCommentCount(n: number | null | undefined): string {
  if (n == null) return '—';
  return n >= 100 ? '100+' : String(n);
}
