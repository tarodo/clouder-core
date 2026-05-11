import { describe, expect, it } from 'vitest';
import {
  tagNameSchema,
  tagColorSchema,
  createTagSchema,
  renameTagSchema,
} from '../tagSchemas';

describe('tagNameSchema', () => {
  it('accepts a normal name', () => {
    expect(tagNameSchema.parse('Vocal')).toBe('Vocal');
  });

  it('trims surrounding whitespace', () => {
    expect(tagNameSchema.parse('  Vocal  ')).toBe('Vocal');
  });

  it('rejects empty / whitespace-only', () => {
    expect(tagNameSchema.safeParse('').success).toBe(false);
    expect(tagNameSchema.safeParse('   ').success).toBe(false);
  });

  it('rejects > 64 characters', () => {
    expect(tagNameSchema.safeParse('x'.repeat(65)).success).toBe(false);
  });

  it('rejects control characters', () => {
    expect(tagNameSchema.safeParse('hello\x00world').success).toBe(false);
  });
});

describe('tagColorSchema', () => {
  it('accepts a valid hex', () => {
    expect(tagColorSchema.parse('#ff8800')).toBe('#ff8800');
  });

  it('accepts null', () => {
    expect(tagColorSchema.parse(null)).toBe(null);
  });

  it('rejects invalid hex', () => {
    expect(tagColorSchema.safeParse('blue').success).toBe(false);
    expect(tagColorSchema.safeParse('#fff').success).toBe(false);
  });
});

describe('createTagSchema / renameTagSchema', () => {
  it('createTagSchema requires name; color optional → null', () => {
    const out = createTagSchema.parse({ name: 'Vocal' });
    expect(out).toEqual({ name: 'Vocal', color: null });
  });

  it('renameTagSchema accepts name only', () => {
    expect(renameTagSchema.parse({ name: 'Vocal F' })).toEqual({
      name: 'Vocal F',
      color: undefined,
    });
  });

  it('renameTagSchema accepts color only', () => {
    expect(renameTagSchema.parse({ color: '#ff8800' })).toEqual({
      name: undefined,
      color: '#ff8800',
    });
  });

  it('renameTagSchema rejects empty payload', () => {
    expect(renameTagSchema.safeParse({}).success).toBe(false);
  });
});
