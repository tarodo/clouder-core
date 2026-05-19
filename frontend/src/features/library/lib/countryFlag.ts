export function countryFlag(iso2: string | null | undefined): string {
  if (!iso2 || iso2.length !== 2) return '';
  const upper = iso2.toUpperCase();
  if (!/^[A-Z]{2}$/.test(upper)) return '';
  const A = 0x1F1E6;
  return String.fromCodePoint(A + upper.charCodeAt(0) - 65)
       + String.fromCodePoint(A + upper.charCodeAt(1) - 65);
}
