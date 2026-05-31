import { ActionIcon, Tooltip } from '@mantine/core';
import { IconBrandYoutube, IconClock } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { PlaylistTrack, YtMusicMatch } from '../lib/playlistTypes';
import { YtMusicReviewPopover } from './YtMusicReviewPopover';

export interface YtMusicBadgeProps {
  match: YtMusicMatch | null | undefined;
  playlistId: string;
  trackId: string;
  track: Pick<PlaylistTrack, 'title' | 'artists'>;
}

// Every state renders as a same-sized ActionIcon so the column never shifts.
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
          aria-label={t('playlists.ytmusic.matched', 'YT Music')}
        >
          <IconBrandYoutube size={18} color="var(--mantine-color-black)" />
        </ActionIcon>
      </Tooltip>
    );
  }

  if (match.status === 'needs_review') {
    return (
      <YtMusicReviewPopover
        playlistId={playlistId} trackId={trackId} track={track} status="needs_review"
      />
    );
  }

  if (match.status === 'not_found') {
    return (
      <YtMusicReviewPopover
        playlistId={playlistId} trackId={trackId} track={track} status="not_found"
      />
    );
  }

  // pending — same-sized disabled icon
  return (
    <Tooltip label={t('playlists.ytmusic.pending', 'Searching YT Music…')}>
      <ActionIcon
        variant="subtle"
        disabled
        aria-label={t('playlists.ytmusic.pending', 'Searching YT Music…')}
      >
        <IconClock size={18} color="var(--mantine-color-gray-5)" />
      </ActionIcon>
    </Tooltip>
  );
}
