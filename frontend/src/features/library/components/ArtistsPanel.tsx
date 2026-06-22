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

  return (
    <Stack gap="sm">
      {artists.map((a) => (
        <ArtistTile key={a.id} artistId={a.id} artistName={a.name} />
      ))}
    </Stack>
  );
}
