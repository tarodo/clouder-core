export function normalizeTagName(input: string): string {
  return input.trim().toLowerCase().split(/\s+/).filter(Boolean).join(' ');
}
