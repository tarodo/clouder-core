import { describe, expect, it } from 'vitest';
import { readTagsUrlState, writeTagsUrlState } from '../tagsUrlState';

describe('readTagsUrlState', () => {
  it('returns defaults for empty params', () => {
    expect(readTagsUrlState(new URLSearchParams())).toEqual({
      selectedIds: [],
      match: 'all',
    });
  });

  it('parses tags csv preserving order', () => {
    expect(readTagsUrlState(new URLSearchParams('tags=tg2,tg1'))).toEqual({
      selectedIds: ['tg2', 'tg1'],
      match: 'all',
    });
  });

  it('drops empty entries from a malformed csv', () => {
    expect(readTagsUrlState(new URLSearchParams('tags=tg1,,tg2,'))).toEqual({
      selectedIds: ['tg1', 'tg2'],
      match: 'all',
    });
  });

  it('parses match=any', () => {
    expect(readTagsUrlState(new URLSearchParams('tags=tg1&match=any'))).toEqual({
      selectedIds: ['tg1'],
      match: 'any',
    });
  });

  it('treats unknown match values as all', () => {
    expect(readTagsUrlState(new URLSearchParams('tags=tg1&match=xor'))).toEqual({
      selectedIds: ['tg1'],
      match: 'all',
    });
  });
});

describe('writeTagsUrlState', () => {
  it('sorts ids and writes csv', () => {
    const next = writeTagsUrlState(new URLSearchParams(), {
      selectedIds: ['tg2', 'tg1'],
      match: 'all',
    });
    expect(next.get('tags')).toBe('tg1,tg2');
  });

  it('omits tags param when ids empty', () => {
    const next = writeTagsUrlState(new URLSearchParams('tags=tg1'), {
      selectedIds: [],
      match: 'all',
    });
    expect(next.has('tags')).toBe(false);
  });

  it('omits match param when default (all)', () => {
    const next = writeTagsUrlState(new URLSearchParams('match=any'), {
      selectedIds: ['tg1'],
      match: 'all',
    });
    expect(next.has('match')).toBe(false);
  });

  it('keeps unrelated params untouched', () => {
    const next = writeTagsUrlState(new URLSearchParams('search=foo'), {
      selectedIds: ['tg1'],
      match: 'any',
    });
    expect(next.get('search')).toBe('foo');
    expect(next.get('tags')).toBe('tg1');
    expect(next.get('match')).toBe('any');
  });
});
