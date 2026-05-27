import { Stack, ActionIcon, Group, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { ArtistDetail } from '../../../api/artists';
import { ARTIST_CHANNELS } from '../lib/artistChannelMeta';

export function ArtistChannelLinks({ info }: { info: ArtistDetail }) {
  const { t } = useTranslation();
  return (
    <Stack gap="xs">
      {ARTIST_CHANNELS.map((ch) => {
        const url = (info as Record<string, unknown>)[ch.field];
        if (typeof url !== 'string' || !url) return null;
        return (
          <Group key={ch.kind} gap="xs">
            <ActionIcon
              component="a"
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              variant="subtle"
              aria-label={t(ch.i18nKey)}
            >
              <ch.Icon size={18} />
            </ActionIcon>
            <Text size="sm">{t(ch.i18nKey)}</Text>
          </Group>
        );
      })}
    </Stack>
  );
}
