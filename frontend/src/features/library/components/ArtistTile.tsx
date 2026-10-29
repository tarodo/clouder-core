import { ActionIcon, Group, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useArtistInfo } from '../hooks/useArtistInfo';
import { ARTIST_CHANNELS } from '../lib/artistChannelMeta';
import { ArtistPreferenceButtons } from './ArtistPreferenceButtons';
import { type AiRep } from './AiRepBadge';
import { Clamped, EntityCard, type EntityStats } from './EntityCard';

const NO_STATS: EntityStats = { tracks: 0, in_categories: 0, in_playlists: 0 };

interface Props {
  artistId: string | null | undefined;
  artistName?: string | null | undefined;
  /** The artist's credits on the track: main, remixer, ... (the card's caption). */
  roles?: readonly string[];
}

interface ArtistInfoView {
  artist_name?: string;
  ai?: AiRep | null;
  country?: string | null;
  active_since?: number | null;
  tagline?: string | null;
  summary?: string | null;
  bio?: string | null;
  notable_collaborators?: string[] | null;
  ai_content?: string | null;
  ai_reasoning?: string | null;
  my_preference?: 'liked' | 'disliked' | null;
  stats?: EntityStats;
}

function pickPreference(value: unknown): 'liked' | 'disliked' | null {
  return value === 'liked' || value === 'disliked' ? value : null;
}

export function ArtistTile({ artistId, artistName, roles = ['main'] }: Props) {
  const { t } = useTranslation();
  const role = roles.map((r) => t(`library.entity.role.${r}`, { defaultValue: r })).join(' · ');
  const query = useArtistInfo(artistId);

  if (!artistId) return null;

  const info = query.data as ArtistInfoView | undefined;
  const displayName = info?.artist_name ?? artistName ?? '';
  const preference = pickPreference(info?.my_preference ?? null);

  const hasEnrichment = !!info && (
    !!info.summary ||
    !!info.bio ||
    !!info.tagline ||
    !!info.country ||
    info.active_since != null ||
    (Array.isArray(info.notable_collaborators) && info.notable_collaborators.length > 0)
  );
  const showFullCard = !query.isLoading && !query.isError && hasEnrichment;

  const collaborators = Array.isArray(info?.notable_collaborators)
    ? info!.notable_collaborators!.filter((a): a is string => typeof a === 'string')
    : [];
  const channels = showFullCard
    ? ARTIST_CHANNELS.flatMap((ch) => {
        const url = (info as Record<string, unknown>)[ch.field];
        if (typeof url !== 'string' || !url) return [];
        return [{ ...ch, url }];
      })
    : [];

  return (
    <EntityCard
      role={role}
      name={displayName || artistId}
      href={`/artists/${artistId}`}
      ai={info?.ai}
      preferences={<ArtistPreferenceButtons artistId={artistId} current={preference} size="sm" />}
      stats={query.isLoading ? undefined : (info?.stats ?? NO_STATS)}
      hasInfo={showFullCard}
    >
      <Stack gap="xs">
        {(info?.country || info?.active_since != null) && (
          <Text size="sm" c="dimmed">
            {[
              info?.country,
              info?.active_since != null &&
                t('library.detail.active_since', { year: info.active_since }),
            ]
              .filter(Boolean)
              .join(' · ')}
          </Text>
        )}
        {info?.tagline && (
          <Text size="sm" fw={500}>
            {info.tagline}
          </Text>
        )}
        {info?.summary && <Clamped text={info.summary} />}
        {collaborators.length > 0 && (
          <Stack gap={2}>
            <Text size="xs" fw={600} c="dimmed">
              {t('library.detail.notable_collaborators')}
            </Text>
            <Text size="sm">{collaborators.join(', ')}</Text>
          </Stack>
        )}
        {channels.length > 0 && (
          <Group gap={6}>
            {channels.map((ch) => (
              <ActionIcon
                key={ch.kind}
                component="a"
                href={ch.url}
                target="_blank"
                rel="noopener noreferrer"
                variant="subtle"
                aria-label={t(ch.i18nKey)}
              >
                <ch.Icon size={16} />
              </ActionIcon>
            ))}
          </Group>
        )}
      </Stack>
    </EntityCard>
  );
}
