import { ActionIcon, Text, Tooltip } from '@mantine/core';
import {
  IconBrandYoutube,
  IconClock,
  IconHelpCircle,
  IconMusicOff,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { YtMusicMatch } from '../lib/playlistTypes';

export interface YtMusicBadgeProps {
  match: YtMusicMatch | null | undefined;
}

export function YtMusicBadge({ match }: YtMusicBadgeProps) {
  const { t } = useTranslation();
  if (!match) return null;

  if (match.status === 'matched' && match.url) {
    const pct = match.confidence != null ? ` (${Math.round(match.confidence * 100)}%)` : '';
    return (
      <Tooltip label={`${t('playlists.ytmusic.matched', 'YT Music')}${pct}`}>
        <ActionIcon
          component="a"
          href={match.url}
          target="_blank"
          rel="noopener noreferrer"
          variant="subtle"
          color="red"
          aria-label={t('playlists.ytmusic.matched', 'YT Music')}
        >
          <IconBrandYoutube size={18} />
        </ActionIcon>
      </Tooltip>
    );
  }

  const { icon, label, color } =
    match.status === 'needs_review'
      ? { icon: <IconHelpCircle size={18} />, label: t('playlists.ytmusic.needsReview', 'Needs review'), color: 'yellow' }
      : match.status === 'not_found'
        ? { icon: <IconMusicOff size={18} />, label: t('playlists.ytmusic.notFound', 'Not on YT Music'), color: 'gray' }
        : { icon: <IconClock size={18} />, label: t('playlists.ytmusic.pending', 'Searching YT Music…'), color: 'gray' };

  return (
    <Tooltip label={label}>
      <Text c={color} component="span" aria-label={label} style={{ display: 'inline-flex' }}>
        {icon}
      </Text>
    </Tooltip>
  );
}
