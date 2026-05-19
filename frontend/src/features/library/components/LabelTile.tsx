import { Anchor, ActionIcon, Badge, Group, Stack, Text, Tooltip } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useLabelInfo } from '../hooks/useLabelInfo';
import { countryFlag } from '../lib/countryFlag';
import { CHANNELS } from '../lib/channelMeta';

interface Props {
  labelId: string | null | undefined;
  styleId: string;
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
}

export function LabelTile({ labelId, styleId }: Props) {
  const { t } = useTranslation();
  const query = useLabelInfo(labelId);

  if (!labelId) return null;
  if (query.isLoading) return null;
  if (query.isError || !query.data) return null;

  const info = query.data as LabelInfoView;
  const detailUrl = `/library/${styleId}/labels/${labelId}`;

  const channels = CHANNELS.flatMap((ch) => {
    const url = (info as Record<string, unknown>)[ch.field];
    if (typeof url !== 'string' || !url) return [];
    return [{ ...ch, url }];
  });

  const aiContent = info.ai_content ?? '';
  const aiReasoning = info.ai_reasoning ?? '';
  const notable = Array.isArray(info.notable_artists)
    ? info.notable_artists.filter((a): a is string => typeof a === 'string')
    : [];

  return (
    <Stack gap="sm" w={320}>
      <Group gap="sm" align="center" wrap="wrap">
        <Anchor component={Link} to={detailUrl} fw={600} size="lg">
          {info.label_name}
        </Anchor>
        {aiContent && (
          <Tooltip
            label={aiReasoning || t('library.detail.ai_reasoning_missing')}
            multiline
            w={280}
            withinPortal
            events={{ hover: true, focus: true, touch: true }}
            styles={{
              tooltip: {
                backgroundColor: 'white',
                color: 'black',
                padding: '12px 16px',
                lineHeight: 1.5,
                border: '1px solid var(--mantine-color-gray-3)',
                boxShadow: 'var(--mantine-shadow-md)',
              },
            }}
          >
            <Badge
              variant="outline"
              style={{
                cursor: 'help',
                backgroundColor: 'white',
                color: 'black',
                borderColor: 'black',
              }}
            >
              AI {aiContent.toUpperCase()}
            </Badge>
          </Tooltip>
        )}
      </Group>
      {(info.country || info.founded_year != null) && (
        <Group gap="xs">
          {info.country && (
            <Text size="sm">
              {countryFlag(info.country)} {info.country}
            </Text>
          )}
          {info.founded_year != null && (
            <Text size="sm" c="dimmed">
              · {t('library.detail.founded', { year: info.founded_year })}
            </Text>
          )}
        </Group>
      )}
      {info.tagline && (
        <Text size="sm" fw={500}>
          {info.tagline}
        </Text>
      )}
      {info.summary && (
        <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
          {info.summary}
        </Text>
      )}
      {notable.length > 0 && (
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
      <Anchor component={Link} to={detailUrl} size="sm">
        {t('library.tile.read_more')}
      </Anchor>
    </Stack>
  );
}
