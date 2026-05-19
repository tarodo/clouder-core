export function truncateTagline(tagline: string | null | undefined, maxChars = 120): string {
  if (!tagline) return '';
  if (tagline.length <= maxChars) return tagline;
  return tagline.slice(0, maxChars - 1) + '…';
}
