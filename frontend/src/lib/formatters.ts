export function formatLength(ms: number | null): string {
  // Em-dash on null OR zero — preserves F1 legacy behavior; covered by tests.
  if (!ms) return '—';
  const total = Math.round(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function formatAdded(iso: string): string {
  const date = new Date(iso);
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(date);
}

export function formatReleaseDate(iso: string | null): string {
  if (!iso) return '—';
  return iso;
}
