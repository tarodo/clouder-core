import { describe, it, expect } from 'vitest';
import {
  playlistNameSchema,
  playlistDescriptionSchema,
  createPlaylistSchema,
} from '../playlistSchemas';

describe('playlistNameSchema', () => {
  it('accepts a 1-char name', () => {
    expect(playlistNameSchema.safeParse('a').success).toBe(true);
  });
  it('rejects empty string', () => {
    expect(playlistNameSchema.safeParse('').success).toBe(false);
  });
  it('rejects > 100 chars', () => {
    expect(playlistNameSchema.safeParse('x'.repeat(101)).success).toBe(false);
  });
  it('accepts exactly 100 chars', () => {
    expect(playlistNameSchema.safeParse('x'.repeat(100)).success).toBe(true);
  });
  it('rejects control characters', () => {
    expect(playlistNameSchema.safeParse('foo\x00bar').success).toBe(false);
  });
  it('trims whitespace', () => {
    const r = playlistNameSchema.safeParse('  hi  ');
    expect(r.success).toBe(true);
    if (r.success) expect(r.data).toBe('hi');
  });
});

describe('playlistDescriptionSchema', () => {
  it('accepts null', () => {
    expect(playlistDescriptionSchema.safeParse(null).success).toBe(true);
  });
  it('accepts empty string and normalises to null', () => {
    const r = playlistDescriptionSchema.safeParse('');
    expect(r.success).toBe(true);
    if (r.success) expect(r.data).toBeNull();
  });
  it('rejects > 300 chars', () => {
    expect(playlistDescriptionSchema.safeParse('x'.repeat(301)).success).toBe(false);
  });
});

describe('createPlaylistSchema', () => {
  it('defaults is_public to false', () => {
    const r = createPlaylistSchema.safeParse({ name: 'My' });
    expect(r.success).toBe(true);
    if (r.success) expect(r.data.is_public).toBe(false);
  });
});
