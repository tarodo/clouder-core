import { useState } from 'react';
import { Badge, Group, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
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
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());

  if (artists.length === 0) return null;

  const [main, ...others] = artists;

  if (!main) return null;

  const expand = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });

  return (
    <Stack gap="sm">
      <Text fw={600} size="sm">
        {t('library.artists_panel.heading')}
      </Text>
      <ArtistTile artistId={main.id} artistName={main.name} />
      {others.length > 0 && (
        <Group gap="xs" wrap="wrap">
          {others.map((a) =>
            expanded.has(a.id) ? (
              <ArtistTile key={a.id} artistId={a.id} artistName={a.name} />
            ) : (
              <Badge
                key={a.id}
                component="button"
                type="button"
                variant="light"
                size="lg"
                style={{ cursor: 'pointer' }}
                onClick={() => expand(a.id)}
                aria-label={t('library.artists_panel.expand_aria', { name: a.name })}
              >
                {a.name}
                {a.role && a.role !== 'main' ? ` · ${a.role}` : ''}
              </Badge>
            ),
          )}
        </Group>
      )}
    </Stack>
  );
}
