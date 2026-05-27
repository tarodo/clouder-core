import { Group, Title, Text, Anchor, Button } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { ArtistDetail } from '../../../api/artists';
import { countryFlag } from '../lib/countryFlag';
import { AiContentBadge } from '../lib/aiContent';
import { ArtistPreferenceButtons } from './ArtistPreferenceButtons';
import { useAuth } from '../../../auth/useAuth';
import { useEnrichArtistAuto } from '../hooks/useEnrichArtistAuto';

interface Props {
  info: ArtistDetail;
  styleId: string;
  artistId: string;
}

export function ArtistDetailHeader({ info, styleId, artistId }: Props) {
  const { t } = useTranslation();
  const { state } = useAuth();
  const isAdmin = state.status === 'authenticated' && state.user.is_admin;
  const enrich = useEnrichArtistAuto();
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

  return (
    <>
      <Anchor component={Link} to={`/library/${styleId}/artists`} size="sm">
        ← {t('library.detail.back_to_list', { style: styleId })}
      </Anchor>
      <Group gap="sm" mt="xs" align="center" wrap="wrap">
        <Title order={2}>{artistName}</Title>
        <AiContentBadge content={aiContent} reasoning={aiReasoning} variant="colored" />
        <ArtistPreferenceButtons artistId={artistId} current={myPreference} size="md" />
        {isAdmin && (
          <Button
            size="xs"
            variant="light"
            loading={enrich.isPending}
            onClick={() => enrich.mutate({ artistId })}
          >
            {t('library.detail.admin_search_now')}
          </Button>
        )}
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
