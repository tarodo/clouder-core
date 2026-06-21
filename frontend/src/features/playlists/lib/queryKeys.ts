// frontend/src/features/playlists/lib/queryKeys.ts

export const playlistsKey = (search?: string | null) =>
  ['playlists', 'list', search ?? null] as const;

export const playlistDetailKey = (id: string) =>
  ['playlists', 'detail', id] as const;

export const playlistTracksKey = (id: string) =>
  ['playlists', 'tracks', id] as const;

export const trackCommentsKey = (trackId: string, limit: number) =>
  ['tracks', 'comments', trackId, limit] as const;
