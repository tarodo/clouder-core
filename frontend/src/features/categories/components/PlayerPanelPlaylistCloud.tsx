import { useMemo } from 'react';
import { Badge, Chip, Group, Stack, Text } from '@mantine/core';
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
  // No `sort` param exists; backend returns items in default ordering. Pull a
  // wide page so the active set fits without pagination on the player panel.
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
    <Stack gap="xs">
      <Group gap="xs" wrap="wrap">
        {playlists.map((pl, idx) => {
          const selected = inPlaylist.has(pl.id);
          const hotkey = idx < HOTKEY_LABELS.length ? HOTKEY_LABELS[idx] : null;
          return (
            <Chip
              key={pl.id}
              checked={selected}
              size="sm"
              variant={selected ? 'filled' : 'outline'}
              onChange={() => (selected ? onRemove(pl.id) : onAdd(pl.id))}
            >
              <Group gap={4} wrap="nowrap" align="center">
                {hotkey ? (
                  <Badge variant="default" size="xs" radius="sm">
                    {hotkey}
                  </Badge>
                ) : null}
                <span>{pl.name}</span>
              </Group>
            </Chip>
          );
        })}
      </Group>
    </Stack>
  );
}
