// frontend/src/features/curate/components/CurateCard.tsx
import { Anchor, Badge, Group, Stack, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useMediaQuery } from '@mantine/hooks';
import type { BucketTrack } from '../../triage/hooks/useBucketTracks';
import { IconExternalLink } from '../../../components/icons';

export interface CurateCardProps {
  track: BucketTrack;
}

function formatLengthMs(ms: number | null): string {
  if (ms === null) return '—';
  const total = Math.round(ms / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function formatBpm(bpm: number | null): string {
  return bpm === null ? '—' : String(bpm);
}

function formatReleaseDate(track: BucketTrack): string {
  return track.spotify_release_date ?? track.publish_date ?? '—';
}

export function CurateCard({ track }: CurateCardProps): JSX.Element {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');

  const titleSize = isMobile ? 'h2' : 'h1';
  const titleOrder: 1 | 2 = isMobile ? 2 : 1;
  const artists = track.artists.join(', ') || '—';

  return (
    <Stack
      gap={isMobile ? 'sm' : 'md'}
      p={isMobile ? 'md' : 'xl'}
      style={{
        background: 'var(--color-bg-elevated)',
        borderRadius: 'var(--radius-lg)',
        boxShadow: 'var(--shadow-sm)',
        minHeight: isMobile ? 'auto' : 480,
      }}
      data-testid="curate-card"
    >
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
          {track.is_ai_suspected && (
            <Badge color="yellow" variant="light" aria-label={t('curate.card.ai_badge_aria')}>
              {t('curate.card.ai_badge')}
            </Badge>
          )}
          <Title order={titleOrder} size={titleSize}>
            {track.title}
          </Title>
          {track.mix_name && (
            <Text c="var(--color-fg-muted)" size={isMobile ? 'sm' : 'md'}>
              {track.mix_name}
            </Text>
          )}
          <Text size={isMobile ? 'sm' : 'md'} c="var(--color-fg)">
            {artists}
          </Text>
        </Stack>
      </Group>

      <Stack gap={4}>
        <Group gap="md" wrap="wrap">
          <Group gap={4} wrap="nowrap">
            <Text size="sm" c="var(--color-fg-muted)">{t('curate.card.label_label')}:</Text>
            <Text size="sm" c="var(--color-fg-muted)">{track.label_name ?? '—'}</Text>
          </Group>
          <Group gap={4} wrap="nowrap">
            <Text size="sm" c="var(--color-fg-muted)">{t('curate.card.bpm_label')}:</Text>
            <Text size="sm" c="var(--color-fg-muted)">{formatBpm(track.bpm)}</Text>
          </Group>
          {track.length_ms !== null && (
            <Group gap={4} wrap="nowrap">
              <Text size="sm" c="var(--color-fg-muted)">{t('curate.card.length_label')}:</Text>
              <Text size="sm" c="var(--color-fg-muted)">{formatLengthMs(track.length_ms)}</Text>
            </Group>
          )}
          <Group gap={4} wrap="nowrap">
            <Text size="sm" c="var(--color-fg-muted)">{t('curate.card.released_label')}:</Text>
            <Text size="sm" c="var(--color-fg-muted)">{formatReleaseDate(track)}</Text>
          </Group>
        </Group>
      </Stack>

      <Group justify="flex-start">
        {track.spotify_id ? (
          <Anchor
            href={`https://open.spotify.com/track/${track.spotify_id}`}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={t('curate.card.open_in_spotify_aria', { title: track.title })}
            c="var(--color-fg)"
            td="none"
          >
            <Group gap={6}>
              <Text>{t('curate.card.open_in_spotify')}</Text>
              <IconExternalLink size={14} />
            </Group>
          </Anchor>
        ) : (
          <Text size="sm" c="var(--color-fg-subtle)">
            {t('curate.card.no_spotify_id')}
          </Text>
        )}
      </Group>
    </Stack>
  );
}
