export type TagsFilterState = {
  selectedIds: string[];
  match: 'all' | 'any';
};

export function readTagsUrlState(params: URLSearchParams): TagsFilterState {
  const tagsRaw = params.get('tags') ?? '';
  const selectedIds = tagsRaw.split(',').filter(Boolean);
  const matchRaw = params.get('match');
  const match: 'all' | 'any' = matchRaw === 'any' ? 'any' : 'all';
  return { selectedIds, match };
}

export function writeTagsUrlState(
  current: URLSearchParams,
  next: TagsFilterState,
): URLSearchParams {
  const params = new URLSearchParams(current);
  if (next.selectedIds.length > 0) {
    const sorted = [...next.selectedIds].sort();
    params.set('tags', sorted.join(','));
  } else {
    params.delete('tags');
  }
  if (next.match === 'any') {
    params.set('match', 'any');
  } else {
    params.delete('match');
  }
  return params;
}
