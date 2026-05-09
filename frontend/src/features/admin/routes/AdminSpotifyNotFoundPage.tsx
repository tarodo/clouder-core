import { Stack, Title } from '@mantine/core';
import { SpotifyNotFoundTable } from '../components/SpotifyNotFoundTable';

export function AdminSpotifyNotFoundPage() {
  return (
    <Stack>
      <Title order={2}>Tracks not on Spotify</Title>
      <SpotifyNotFoundTable />
    </Stack>
  );
}
