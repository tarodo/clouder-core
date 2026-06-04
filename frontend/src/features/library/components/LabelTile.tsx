import { Anchor, ActionIcon, Group, Stack, Text } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useLabelInfo } from '../hooks/useLabelInfo';
import { countryFlag } from '../lib/countryFlag';
import { CHANNELS } from '../lib/channelMeta';
import { AiContentBadge } from '../lib/aiContent';
import { LabelPreferenceButtons } from './LabelPreferenceButtons';

interface Props {
  labelId: string | null | undefined;
  labelName?: string | null | undefined;
}

interface LabelInfoView {
  label_name?: string;
  country?: string | null;
  founded_year?: number | null;
  tagline?: string | null;
  summary?: string | null;
  notable_artists?: string[] | null;
  ai_content?: string | null;
  ai_reasoning?: string | null;
  my_preference?: 'liked' | 'disliked' | null;
}

function pickPreference(value: unknown): 'liked' | 'disliked' | null {
  return value === 'liked' || value === 'disliked' ? value : null;
}

export function LabelTile({ labelId, labelName }: Props) {
  const { t } = useTranslation();
  const query = useLabelInfo(labelId);

  if (!labelId) return null;

  const info = query.data as LabelInfoView | undefined;
  const displayName = info?.label_name ?? labelName ?? '';
  const preference = pickPreference(info?.my_preference ?? null);

  // The user-facing detail endpoint now always returns 200 once a label
  // exists, but the response is `{label_name, my_preference}` when no
  // enrichment row exists. Treat such a response as "info missing" so
  // the tile stays in minimal mode (name + buttons only).
  const hasEnrichment = !!info && (
    !!info.summary ||
    !!info.tagline ||
    !!info.country ||
    info.founded_year != null ||
    (Array.isArray(info.notable_artists) && info.notable_artists.length > 0)
  );
  const showFullCard = !query.isLoading && !query.isError && hasEnrichment;

  const aiContent = info?.ai_content ?? '';
  const aiReasoning = info?.ai_reasoning ?? '';
  const notable = Array.isArray(info?.notable_artists)
    ? info!.notable_artists!.filter((a): a is string => typeof a === 'string')
    : [];
  const channels = showFullCard
    ? CHANNELS.flatMap((ch) => {
        const url = (info as Record<string, unknown>)[ch.field];
        if (typeof url !== 'string' || !url) return [];
        return [{ ...ch, url }];
      })
    : [];

  return (
    <Stack gap="sm" maw={320}>
      <Group gap="sm" align="center" wrap="wrap">
        <Anchor component={Link} to={`/labels/${labelId}`} fw={600} size="lg">
          {displayName || labelId}
        </Anchor>
        {showFullCard && (
          <AiContentBadge content={aiContent} reasoning={aiReasoning} variant="outline" />
        )}
        <LabelPreferenceButtons labelId={labelId} current={preference} size="sm" />
      </Group>
      {showFullCard && (info?.country || info?.founded_year != null) && (
        <Group gap="xs">
          {info?.country && (
            <Text size="sm">
              {countryFlag(info.country)} {info.country}
            </Text>
          )}
          {info?.founded_year != null && (
            <Text size="sm" c="dimmed">
              · {t('library.detail.founded', { year: info.founded_year })}
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
      {showFullCard && notable.length > 0 && (
        <Stack gap={2}>
          <Text size="xs" fw={600} c="dimmed">
            {t('library.detail.notable_artists')}
          </Text>
          <Text size="sm">{notable.join(', ')}</Text>
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
