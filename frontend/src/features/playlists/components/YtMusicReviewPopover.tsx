import { useEffect, useState } from 'react';
import {
  ActionIcon, Anchor, Button, Group, Popover, Stack, Text, TextInput, Tooltip,
} from '@mantine/core';
import { IconHelpCircle, IconExternalLink, IconMusicOff } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { PlaylistTrack } from '../lib/playlistTypes';
import { useMatchCandidates } from '../hooks/useMatchCandidates';
import { useResolveMatch } from '../hooks/useResolveMatch';
import { parseYtVideoId } from '../lib/parseYtVideoId';

export interface YtMusicReviewPopoverProps {
  playlistId: string;
  trackId: string;
  track: Pick<PlaylistTrack, 'title' | 'artists'>;
  /** Which actionable state opened the popover. */
  status: 'needs_review' | 'not_found';
}

export function YtMusicReviewPopover({ playlistId, trackId, track, status }: YtMusicReviewPopoverProps) {
  const { t } = useTranslation();
  const [opened, setOpened] = useState(false);
  const [link, setLink] = useState('');
  const [linkError, setLinkError] = useState<string | null>(null);
  // not_found has no pending review row, so there are no candidates to fetch.
  const isReview = status === 'needs_review';
  const candidates = useMatchCandidates(playlistId, trackId, opened && isReview);
  const resolve = useResolveMatch(playlistId, trackId);

  useEffect(() => {
    if (!opened) {
      setLink('');
      setLinkError(null);
    }
  }, [opened]);

  const accept = (vendorTrackId: string) =>
    resolve.mutate({ action: 'accept', vendorTrackId }, { onSuccess: () => setOpened(false) });

  const acceptLink = () => {
    const id = parseYtVideoId(link);
    if (!id) { setLinkError(t('playlists.ytmusic.badLink', 'Invalid YT Music link')); return; }
    setLinkError(null);
    accept(id);
  };

  const trigger = isReview
    ? {
        icon: <IconHelpCircle size={18} color="var(--mantine-color-yellow-6)" />,
        label: t('playlists.ytmusic.needsReview', 'Needs review'),
      }
    : {
        icon: <IconMusicOff size={18} color="var(--mantine-color-gray-5)" />,
        label: t('playlists.ytmusic.addManually', 'Not on YT Music — add a link'),
      };

  return (
    <Popover opened={opened} onChange={setOpened} width={360} position="bottom-end" withArrow>
      <Popover.Target>
        <Tooltip label={trigger.label}>
          <ActionIcon variant="subtle"
            aria-label={t('playlists.ytmusic.review', 'Review YT Music match')}
            onClick={() => setOpened((o) => !o)}>
            {trigger.icon}
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs">
          <Text fw={600} size="sm">{track.title}</Text>
          <Text c="dimmed" size="xs">{track.artists.map((a) => a.name).join(', ')}</Text>

          {isReview && candidates.isLoading && (
            <Text size="xs" c="dimmed">{t('playlists.ytmusic.loading', 'Loading…')}</Text>
          )}
          {isReview && candidates.isError && (
            <Text size="xs" c="red">
              {t('playlists.ytmusic.loadError', 'Could not load candidates')}
            </Text>
          )}
          {isReview && candidates.data?.candidates.map((c) => (
            <Group key={c.vendor_track_id} justify="space-between" wrap="nowrap" gap="xs">
              <Stack gap={0} style={{ minWidth: 0 }}>
                <Text size="sm" truncate>{c.title}</Text>
                <Text size="xs" c="dimmed" truncate>
                  {c.artists.join(', ')}{c.score != null ? ` · ${c.score.toFixed(2)}` : ''}
                </Text>
              </Stack>
              <Group gap={4} wrap="nowrap">
                <Anchor href={c.url} target="_blank" rel="noopener noreferrer"
                  aria-label={t('playlists.ytmusic.openOnYt', 'Open on YT Music')}>
                  <IconExternalLink size={16} />
                </Anchor>
                <Button size="compact-xs" disabled={resolve.isPending}
                  onClick={() => accept(c.vendor_track_id)}>
                  {t('playlists.ytmusic.accept', 'Accept')}
                </Button>
              </Group>
            </Group>
          ))}

          {!isReview && (
            <Text size="xs" c="dimmed">
              {t('playlists.ytmusic.noAutoMatch', 'No automatic match. Paste a YT Music link:')}
            </Text>
          )}

          <TextInput size="xs" placeholder="https://music.youtube.com/watch?v=…"
            value={link} error={linkError ?? undefined}
            onChange={(e) => setLink(e.currentTarget.value)} />
          <Group justify="space-between">
            <Button size="compact-xs" variant="light" onClick={acceptLink}
              disabled={resolve.isPending || !link.trim()}>
              {t('playlists.ytmusic.useLink', 'Use link')}
            </Button>
            {isReview && (
              <Button size="compact-xs" variant="subtle" color="gray" disabled={resolve.isPending}
                onClick={() => resolve.mutate({ action: 'reject' }, { onSuccess: () => setOpened(false) })}>
                {t('playlists.ytmusic.notOnYt', 'Not on YT')}
              </Button>
            )}
          </Group>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
