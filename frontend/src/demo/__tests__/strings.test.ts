import { describe, expect, it } from 'vitest';
import en from '../../i18n/en.json';
import { DEMO_STRINGS } from '../start';

function keys(o: object, prefix = ''): string[] {
  return Object.entries(o).flatMap(([k, v]) =>
    v && typeof v === 'object' ? keys(v as object, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
}

describe('demo strings', () => {
  it('only override keys the app has', () => {
    const known = new Set(keys(en));
    expect(keys(DEMO_STRINGS).filter((k) => !known.has(k))).toEqual([]);
  });

  it('turn a refused write into a demo message, not a generic error', () => {
    const overridden = new Set(keys(DEMO_STRINGS));
    for (const key of [
      'errors.forbidden',
      'errors.unknown',
      'triage.toast.generic_error',
      'categories.toast.generic_error',
      'playlists.toast.generic_error',
      'playlists.copy.failed',
    ]) {
      expect(overridden.has(key), key).toBe(true);
    }
  });
});
