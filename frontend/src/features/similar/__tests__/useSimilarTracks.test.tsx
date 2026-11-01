import { describe, expect, it } from 'vitest';
import { QueryClient, type InfiniteData } from '@tanstack/react-query';
import { patchEntityTrack, type EntityTracksPage } from '../../library/hooks/useEntityTracks';
import { similarTrackKey } from '../useSimilarTracks';

describe('similar lists in the entity cache', () => {
  it('a category toggle patches a similar list row', () => {
    const qc = new QueryClient();
    const page = { items: [{ id: 't1', categories: [] }], total: 1, limit: 50, offset: 0 };
    qc.setQueryData(similarTrackKey('s'), { pages: [page], pageParams: [0] });
    patchEntityTrack(qc, 't1', (t) => ({ ...t, categories: [{ id: 'c1', name: 'Rollers' }] }));
    const data = qc.getQueryData<InfiniteData<EntityTracksPage>>(similarTrackKey('s'));
    expect(data?.pages[0]?.items[0]?.categories).toEqual([{ id: 'c1', name: 'Rollers' }]);
  });
});
