import { describe, it, expect } from 'vitest';
import { parseEnv } from '../env';

describe('parseEnv', () => {
  it('returns base URL when set', () => {
    expect(parseEnv({ VITE_API_BASE_URL: 'https://api.example.com' })).toEqual({
      VITE_API_BASE_URL: 'https://api.example.com',
    });
  });

  it('throws when base URL missing', () => {
    expect(() => parseEnv({})).toThrow(/VITE_API_BASE_URL/);
  });

  it('throws when base URL is not a URL', () => {
    expect(() => parseEnv({ VITE_API_BASE_URL: 'not a url' })).toThrow();
  });
});
