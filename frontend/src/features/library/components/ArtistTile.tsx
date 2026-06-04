import { Anchor, ActionIcon, Group, Stack, Text } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useArtistInfo } from '../hooks/useArtistInfo';
import { countryFlag } from '../lib/countryFlag';
import { ARTIST_CHANNELS } from '../lib/artistChannelMeta';
import { AiContentBadge } from '../lib/aiContent';
import { ArtistPreferenceButtons } from './ArtistPreferenceButtons';

interface Props {
  artistId: string | null | undefined;
  artistName?: string | null | undefined;
}

interface ArtistInfoView {
  artist_name?: string;
  country?: string | null;
  active_since?: number | null;
  tagline?: string | null;
  summary?: string | null;
  bio?: string | null;
  notable_collaborators?: string[] | null;
  ai_content?: string | null;
  ai_reasoning?: string | null;
  my_preference?: 'liked' | 'disliked' | null;
}

function pickPreference(value: unknown): 'liked' | 'disliked' | null {
  return value === 'liked' || value === 'disliked' ? value : null;
}

export function ArtistTile({ artistId, artistName }: Props) {
  const { t } = useTranslation();
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

  const aiContent = info?.ai_content ?? '';
  const aiReasoning = info?.ai_reasoning ?? '';
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

  const nameNode = (
    <Anchor component={Link} to={`/artists/${artistId}`} fw={600} size="lg">
      {displayName || artistId}
    </Anchor>
  );

  return (
    <Stack gap="sm" w={320}>
      <Group gap="sm" align="center" wrap="wrap">
        {nameNode}
        {showFullCard && (
          <AiContentBadge content={aiContent} reasoning={aiReasoning} variant="outline" />
        )}
        <ArtistPreferenceButtons artistId={artistId} current={preference} size="sm" />
      </Group>
      {showFullCard && (info?.country || info?.active_since != null) && (
        <Group gap="xs">
          {info?.country && (
            <Text size="sm">
              {countryFlag(info.country)} {info.country}
            </Text>
          )}
          {info?.active_since != null && (
            <Text size="sm" c="dimmed">
              · {t('library.detail.active_since', { year: info.active_since })}
            </Text>
          )}
        </Group>
      )}
      {showFullCard && info?.tagline && (
        <Text size="sm" fw={500}>
          {info.tagline}
        </Text>
      )}
      {showFullCard && info?.summary && (
        <Text size="sm" className="prewrap">
          {info.summary}
        </Text>
      )}
      {showFullCard && collaborators.length > 0 && (
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
  );
}
