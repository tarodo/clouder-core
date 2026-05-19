import { describe, it, expect } from 'vitest';
import { pickTopChannels } from '../pickTopChannels';

describe('pickTopChannels', () => {
  it('prioritises website > soundcloud > bandcamp', () => {
    const result = pickTopChannels({
      website: 'https://a',
      bandcamp_url: 'https://b',
      soundcloud_url: 'https://c',
    }, 3);
    expect(result.map(c => c.kind)).toEqual(['website', 'soundcloud', 'bandcamp']);
  });

  it('skips null URLs', () => {
    const result = pickTopChannels({
      website: null,
      soundcloud_url: 'https://s',
      bandcamp_url: null,
    }, 3);
    expect(result.map(c => c.kind)).toEqual(['soundcloud']);
  });

  it('respects the limit', () => {
    const result = pickTopChannels({
      website: 'a', soundcloud_url: 'b', bandcamp_url: 'c',
      beatport_url: 'd', instagram_url: 'e',
    }, 2);
    expect(result).toHaveLength(2);
  });
});
