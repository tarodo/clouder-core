import { Badge, Button, Card, Group, Skeleton, Stack, Table, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { formatLength, formatReleaseDate } from '../../../lib/formatters';
import { AiBadge } from '../../playback/AiBadge';
import { PlayPauseButton } from '../../playback/PlayPauseButton';
import { TrackKey } from '../../playback/TrackKey';
import { AiRepBadge, NamesWithAi } from './AiRepBadge';
import type { EntityKind, EntityTrack } from '../hooks/useEntityTracks';

const NOWRAP = { whiteSpace: 'nowrap' } as const;

export interface EntityTrackListProps {
  kind: EntityKind;
  items: EntityTrack[];
  variant: 'desktop' | 'mobile';
  loading: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
  currentTrackId: string | null;
  playing: boolean;
  onPlay: (track: EntityTrack) => void;
  onToggle: () => void;
}

/** Where the user already put the track: category names, and a mark for playlists. */
function Mine({ track }: { track: EntityTrack }) {
  const { t } = useTranslation();
  if (track.categories.length === 0 && track.playlists.length === 0) return null;
  return (
    <Group gap={4} wrap="wrap">
      {track.categories.map((c) => (
        <Badge key={c.id} size="sm" variant="light" color="gray" radius="sm">
          {c.name}
        </Badge>
      ))}
      {track.playlists.length > 0 ? (
        <Badge size="sm" variant="outline" color="gray" radius="sm">
          {t('library.entity_tracks.in_playlists', { count: track.playlists.length })}
        </Badge>
      ) : null}
    </Group>
  );
}

export function EntityTrackList(props: EntityTrackListProps) {
  const { t } = useTranslation();
  const { kind, items, variant, loading, currentTrackId, playing, onPlay, onToggle } = props;

  if (loading) {
    return (
      <Stack gap="xs" aria-busy>
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} height={48} radius="sm" />
        ))}
      </Stack>
    );
  }
  if (items.length === 0) {
    return <Text c="dimmed">{t('library.entity_tracks.empty')}</Text>;
  }

  const play = (track: EntityTrack) => {
    const isCurrent = track.id === currentTrackId;
    return (
      <PlayPauseButton
        isCurrent={isCurrent}
        isPlaying={isCurrent && playing}
        canPlay={!!track.spotify_id}
        onPlay={() => onPlay(track)}
        onToggle={isCurrent ? onToggle : () => onPlay(track)}
        playLabel={t('categories.tracks_table.play_aria')}
        pauseLabel={t('categories.tracks_table.pause_aria')}
        unavailableLabel={t('categories.tracks_table.play_unavailable')}
      />
    );
  };
  const title = (track: EntityTrack) => (
    <Stack gap={0} miw={0}>
      <Group gap={6} wrap="nowrap">
        <Text fw={500} truncate>
          {track.title}
        </Text>
        <AiBadge verdict={track.ai_verdict} />
      </Group>
      {track.mix_name ? (
        <Text size="xs" c="dimmed" truncate>
          {track.mix_name}
        </Text>
      ) : null}
    </Stack>
  );

  const more = props.hasMore ? (
    <Group justify="center" mt="sm">
      <Button variant="default" loading={props.loadingMore} onClick={props.onMore}>
        {t('library.entity_tracks.more')}
      </Button>
    </Group>
  ) : null;

  if (variant === 'mobile') {
    return (
      <Stack gap="xs">
        {items.map((track) => (
          <Card
            key={track.id}
            withBorder
            padding="sm"
            data-current={track.id === currentTrackId || undefined}
            bg={track.id === currentTrackId ? 'var(--mantine-color-default-hover)' : undefined}
          >
            <Group gap="xs" wrap="nowrap" align="flex-start">
              {play(track)}
              <Stack gap={4} miw={0} style={{ flex: 1 }}>
                {title(track)}
                <Text size="sm" truncate>
                  <NamesWithAi items={track.artists} />
                </Text>
                {kind === 'artist' && track.label ? (
                  <Text size="xs" c="dimmed" truncate>
                    {track.label.name}
                    <AiRepBadge rep={track.label.ai} ml={4} />
                  </Text>
                ) : null}
                <Group gap="md">
                  <Text size="xs" c="dimmed" className="font-mono">
                    {track.bpm ?? '—'} BPM
                  </Text>
                  <TrackKey camelot={track.key_camelot} name={track.key_name} size="xs" />
                  <Text size="xs" c="dimmed" className="font-mono">
                    {formatReleaseDate(track.release_date)}
                  </Text>
                </Group>
                <Mine track={track} />
              </Stack>
            </Group>
          </Card>
        ))}
        {more}
      </Stack>
    );
  }

  return (
    <>
      <Table.ScrollContainer minWidth={760}>
        <Table verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('library.entity_tracks.col_title')}</Table.Th>
              <Table.Th>{t('library.entity_tracks.col_artists')}</Table.Th>
              {kind === 'artist' ? <Table.Th>{t('library.entity_tracks.col_label')}</Table.Th> : null}
              <Table.Th>{t('library.entity_tracks.col_style')}</Table.Th>
              <Table.Th>{t('library.entity_tracks.col_key')}</Table.Th>
              <Table.Th>BPM</Table.Th>
              <Table.Th>{t('library.entity_tracks.col_length')}</Table.Th>
              <Table.Th>{t('library.entity_tracks.col_released')}</Table.Th>
              <Table.Th>{t('library.entity_tracks.col_mine')}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((track) => (
              <Table.Tr
                key={track.id}
                data-current={track.id === currentTrackId || undefined}
                bg={track.id === currentTrackId ? 'var(--mantine-color-default-hover)' : undefined}
              >
                <Table.Td maw={320}>
                  <Group gap="xs" wrap="nowrap">
                    {play(track)}
                    {title(track)}
                  </Group>
                </Table.Td>
                <Table.Td>
                  <NamesWithAi items={track.artists} />
                </Table.Td>
                {kind === 'artist' ? (
                  <Table.Td>
                    <NamesWithAi items={track.label ? [track.label] : []} />
                  </Table.Td>
                ) : null}
                <Table.Td>{track.style?.name ?? '—'}</Table.Td>
                <Table.Td>
                  <TrackKey camelot={track.key_camelot} name={track.key_name} />
                </Table.Td>
                <Table.Td className="font-mono">{track.bpm ?? '—'}</Table.Td>
                <Table.Td className="font-mono" style={NOWRAP}>
                  {formatLength(track.length_ms)}
                </Table.Td>
                <Table.Td className="font-mono" style={NOWRAP}>
                  {formatReleaseDate(track.release_date)}
                </Table.Td>
                <Table.Td>
                  <Mine track={track} />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {more}
    </>
  );
}
