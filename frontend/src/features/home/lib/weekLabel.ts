export function weekLabel(isoDate: string): string {
  const d = new Date(isoDate + 'T00:00:00Z');
  if (Number.isNaN(d.getTime())) return '';
  // ISO week algorithm: shift to nearest Thursday, then week = ((thu - jan1) / 7) + 1
  const target = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const dayNr = (target.getUTCDay() + 6) % 7; // Mon=0 .. Sun=6
  target.setUTCDate(target.getUTCDate() - dayNr + 3); // nearest Thursday
  const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
  const diff = target.getTime() - firstThursday.getTime();
  const week = 1 + Math.round(diff / (7 * 24 * 60 * 60 * 1000));
  const year = target.getUTCFullYear();
  return `${year}-W${String(week).padStart(2, '0')}`;
}
