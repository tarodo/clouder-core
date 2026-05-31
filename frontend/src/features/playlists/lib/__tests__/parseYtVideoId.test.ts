import { describe, it, expect } from 'vitest';
import { parseYtVideoId } from '../parseYtVideoId';

describe('parseYtVideoId', () => {
  it('parses music.youtube.com watch url', () => {
    expect(parseYtVideoId('https://music.youtube.com/watch?v=dQw4w9WgXcQ')).toBe('dQw4w9WgXcQ');
  });
  it('parses youtube.com watch url with extra params', () => {
    expect(parseYtVideoId('https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=x')).toBe('dQw4w9WgXcQ');
  });
  it('parses youtu.be short url', () => {
    expect(parseYtVideoId('https://youtu.be/dQw4w9WgXcQ')).toBe('dQw4w9WgXcQ');
  });
  it('accepts a bare 11-char id', () => {
    expect(parseYtVideoId('dQw4w9WgXcQ')).toBe('dQw4w9WgXcQ');
  });
  it('returns null for junk', () => {
    expect(parseYtVideoId('not a link')).toBeNull();
    expect(parseYtVideoId('https://music.youtube.com/playlist?list=x')).toBeNull();
  });
});
