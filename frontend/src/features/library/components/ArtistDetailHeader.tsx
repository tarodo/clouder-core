import { Group, Title, Text, Anchor, Button } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useBackOrFallback } from '../hooks/useBackOrFallback';
import type { ArtistDetail } from '../../../api/artists';
import { countryFlag } from '../lib/countryFlag';
import { ArtistPreferenceButtons } from './ArtistPreferenceButtons';
import { useAuth } from '../../../auth/useAuth';
import { useEnrichArtistAuto } from '../hooks/useEnrichArtistAuto';

interface Props {
  info: ArtistDetail;
  artistId: string;
}

export function ArtistDetailHeader({ info, artistId }: Props) {
  const { t } = useTranslation();
  const goBack = useBackOrFallback('/library');
  const { state } = useAuth();
  const isAdmin = state.status === 'authenticated' && state.user.is_admin;
  const enrich = useEnrichArtistAuto();
  const rec = info as Record<string, unknown>;
  const artistName = typeof rec.artist_name === 'string' ? rec.artist_name : '';
  const country = typeof rec.country === 'string' ? rec.country : '';
  const activeSince =
    typeof rec.active_since === 'number' ? rec.active_since : null;
  const myPreference =
    rec.my_preference === 'liked' || rec.my_preference === 'disliked'
      ? rec.my_preference
      : null;

  return (
    <>
      <Group gap="sm" align="center" wrap="wrap">
        <Anchor component="button" type="button" onClick={goBack} size="sm">
          {t('library.detail.back')}
        </Anchor>
        <Title order={2}>{artistName}</Title>
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
