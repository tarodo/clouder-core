import { Group, Title, Text, Anchor, Badge, Tooltip } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { ArtistDetail } from '../../../api/artists';
import { countryFlag } from '../lib/countryFlag';
import { ArtistPreferenceButtons } from './ArtistPreferenceButtons';

interface Props {
  info: ArtistDetail;
  styleId: string;
  artistId: string;
}

const AI_COLOR: Record<string, string> = {
  none_detected: 'green',
  unknown: 'gray',
  suspected: 'yellow',
  confirmed: 'red',
};

function formatAiContent(value: string): string {
  return `AI ${value.toUpperCase()}`;
}

export function ArtistDetailHeader({ info, styleId, artistId }: Props) {
  const { t } = useTranslation();
  const rec = info as Record<string, unknown>;
  const artistName = typeof rec.artist_name === 'string' ? rec.artist_name : '';
  const country = typeof rec.country === 'string' ? rec.country : '';
  const activeSince =
    typeof rec.active_since === 'number' ? rec.active_since : null;
  const aiContent = typeof rec.ai_content === 'string' ? rec.ai_content : '';
  const aiReasoning =
    typeof rec.ai_reasoning === 'string' ? rec.ai_reasoning : '';
  const myPreference =
    rec.my_preference === 'liked' || rec.my_preference === 'disliked'
      ? rec.my_preference
      : null;

  const aiBadge = aiContent ? (
    <Tooltip
      label={aiReasoning || t('library.detail.ai_reasoning_missing')}
      multiline
      w={340}
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
        color={AI_COLOR[aiContent] ?? 'gray'}
        variant="light"
        style={{ cursor: 'help' }}
      >
        {formatAiContent(aiContent)}
      </Badge>
    </Tooltip>
  ) : null;

  return (
    <>
      <Anchor component={Link} to={`/library/${styleId}/artists`} size="sm">
        ← {t('library.detail.back_to_list', { style: styleId })}
      </Anchor>
      <Group gap="sm" mt="xs" align="center" wrap="wrap">
        <Title order={2}>{artistName}</Title>
        {aiBadge}
        <ArtistPreferenceButtons artistId={artistId} current={myPreference} size="md" />
      </Group>
      <Group gap="xs" mt="xs">
        {country && (
          <Text>
            {countryFlag(country)} {country}
          </Text>
        )}
        {activeSince !== null && (
          <Text c="dimmed">
            · {t('library.detail.active_since', { year: activeSince })}
          </Text>
        )}
      </Group>
    </>
  );
}
