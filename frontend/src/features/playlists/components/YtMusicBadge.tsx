import { ActionIcon, Text, Tooltip } from '@mantine/core';
import {
  IconBrandYoutube,
  IconClock,
  IconMusicOff,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { PlaylistTrack, YtMusicMatch } from '../lib/playlistTypes';
import { YtMusicReviewPopover } from './YtMusicReviewPopover';

export interface YtMusicBadgeProps {
  match: YtMusicMatch | null | undefined;
  playlistId: string;
  trackId: string;
  track: Pick<PlaylistTrack, 'title' | 'artists'>;
}

export function YtMusicBadge({ match, playlistId, trackId, track }: YtMusicBadgeProps) {
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

  if (match.status === 'needs_review') {
    return <YtMusicReviewPopover playlistId={playlistId} trackId={trackId} track={track} />;
  }

  const { icon, label, color } =
    match.status === 'not_found'
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
