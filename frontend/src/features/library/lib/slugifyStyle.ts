/**
 * Slugify a style display name to its URL/filter form.
 *
 * Mirrors the SQL expression used by the backend in
 * `src/collector/label_enrichment/repository.py`:
 *
 *   TRIM(BOTH '-' FROM
 *     LOWER(REGEXP_REPLACE(
 *       REPLACE(s.name, '&', 'and'),
 *       '[^a-zA-Z0-9]+', '-', 'g'
 *     ))
 *   )
 *
 * Example: "Drum & Bass" -> "drum-and-bass".
 */
export function slugifyStyle(name: string): string {
  return name
    .replace(/&/g, 'and')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
