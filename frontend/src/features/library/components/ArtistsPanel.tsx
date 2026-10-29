import { Stack } from '@mantine/core';
import { ArtistTile } from './ArtistTile';

export interface PanelArtist {
  id: string;
  name: string;
  role?: string;
}

interface Props {
  artists: ReadonlyArray<PanelArtist>;
}

export function ArtistsPanel({ artists }: Props) {
  if (artists.length === 0) return null;

  // One card per artist: credited twice (main and remixer), it shows both credits.
  const byId = new Map<string, { name: string; roles: string[] }>();
  for (const a of artists) {
    const seen = byId.get(a.id);
    if (seen) seen.roles.push(a.role ?? 'main');
    else byId.set(a.id, { name: a.name, roles: [a.role ?? 'main'] });
  }
  return (
    <Stack gap="sm">
      {[...byId].map(([id, a]) => (
        <ArtistTile key={id} artistId={id} artistName={a.name} roles={a.roles} />
      ))}
    </Stack>
  );
}
