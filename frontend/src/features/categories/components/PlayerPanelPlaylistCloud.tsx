import { useMemo } from 'react';
import { Badge, Button, SimpleGrid, Text } from '@mantine/core';
import { usePlaylists } from '../../playlists/hooks/usePlaylists';

export interface PlayerPanelPlaylistCloudProps {
  trackId: string;
  trackPlaylistIds: readonly string[];
  onAdd: (playlistId: string) => void;
  onRemove: (playlistId: string) => void;
}

const HOTKEY_LABELS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'];

export function PlayerPanelPlaylistCloud(props: PlayerPanelPlaylistCloudProps) {
  const { trackPlaylistIds, onAdd, onRemove } = props;
  // usePlaylists signature: { search?, status?, limit?, offset?, enabled? }.
  // Pull a wide page so the active set fits without pagination on the panel.
  const query = usePlaylists({ status: 'active', limit: 100 });
  const playlists = query.data?.items ?? [];

  const inPlaylist = useMemo(() => new Set(trackPlaylistIds), [trackPlaylistIds]);

  if (playlists.length === 0) {
    return (
      <Text c="dimmed" size="sm">
        No active playlists
      </Text>
    );
  }

  return (
    <SimpleGrid cols={2} spacing="xs" verticalSpacing="xs">
      {playlists.map((pl, idx) => {
        const selected = inPlaylist.has(pl.id);
        const hotkey = idx < HOTKEY_LABELS.length ? HOTKEY_LABELS[idx] : null;
        return (
          <Button
            key={pl.id}
            fullWidth
            size="sm"
            variant={selected ? 'filled' : 'default'}
            onClick={() => (selected ? onRemove(pl.id) : onAdd(pl.id))}
            leftSection={
              hotkey ? (
                <Badge variant="default" size="xs" radius="sm">
                  {hotkey}
                </Badge>
              ) : undefined
            }
            styles={{
              label: { whiteSpace: 'normal' },
              inner: { justifyContent: 'flex-start' },
            }}
          >
            {pl.name} ({pl.track_count})
          </Button>
        );
      })}
    </SimpleGrid>
  );
}
