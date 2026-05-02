import { describe, it, expect } from 'vitest';
import { categoryNameSchema, createCategorySchema } from '../categorySchemas';

describe('categoryNameSchema', () => {
  it('rejects empty', () => {
    expect(categoryNameSchema.safeParse('').success).toBe(false);
  });

  it('rejects whitespace-only', () => {
    const r = categoryNameSchema.safeParse('   ');
    expect(r.success).toBe(false);
  });

  it('trims', () => {
    expect(categoryNameSchema.parse('  Tech House  ')).toBe('Tech House');
  });

  it('accepts 64 chars after trim', () => {
    expect(categoryNameSchema.safeParse('a'.repeat(64)).success).toBe(true);
  });

  it('rejects 65 chars', () => {
    expect(categoryNameSchema.safeParse('a'.repeat(65)).success).toBe(false);
  });

  it('rejects ASCII control bytes', () => {
    expect(categoryNameSchema.safeParse('hi\x00there').success).toBe(false);
    expect(categoryNameSchema.safeParse('hi\x1fthere').success).toBe(false);
    expect(categoryNameSchema.safeParse('hi\x7fthere').success).toBe(false);
  });

  it('accepts unicode', () => {
    expect(categoryNameSchema.safeParse('Tech House — Deep ✦').success).toBe(true);
  });
});

describe('createCategorySchema', () => {
  it('round-trips name', () => {
    expect(createCategorySchema.parse({ name: ' Deep  ' })).toEqual({ name: 'Deep' });
  });
});
