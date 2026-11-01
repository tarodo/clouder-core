import { Anchor, Group, Stack, Text, Title } from '@mantine/core';
import { Navigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { EmptyState } from '../../components/EmptyState';
import { ArtistLinks } from '../library/components/EntityLinks';
import { TracksSection } from '../library/components/EntityTracksSection';
import { useBackOrFallback } from '../library/hooks/useBackOrFallback';
import { useSimilarTracks } from './useSimilarTracks';

/** The tracks that sound like :trackId, in its style; the seed first. Re-mounts per seed. */
export function SimilarTracksPage() {
  const { trackId } = useParams<{ trackId: string }>();
  if (!trackId) return <Navigate to="/library" replace />;
  return <SimilarTo key={trackId} trackId={trackId} />;
}

function SimilarTo({ trackId }: { trackId: string }) {
  const { t } = useTranslation();
  const goBack = useBackOrFallback('/library');
  const query = useSimilarTracks(trackId);
  const body = query.data?.pages[0];
  const seed = body?.seed;

  if (body && !seed) {
    return <EmptyState variant="page" title={t('similar.title')} body={t('similar.not_found')} />;
  }
  return (
    <Stack gap="lg">
      <Stack gap={4}>
        {/* on the title row: no row of its own above the tracks */}
        <Group gap="sm" align="center" wrap="wrap">
          <Anchor component="button" type="button" onClick={goBack} size="sm">
            {t('library.detail.back')}
          </Anchor>
          <Title order={2}>{t('similar.title')}</Title>
        </Group>
        {seed ? (
          <Text c="dimmed">
            {seed.title}
            {seed.mix_name ? ` (${seed.mix_name})` : ''} — <ArtistLinks artists={seed.artists} />
            {seed.style ? ` · ${seed.style.name}` : ''}
          </Text>
        ) : null}
      </Stack>
      {body && !body.profiled ? (
        <Text c="dimmed">{t('similar.unprofiled')}</Text>
      ) : (
        <TracksSection
          source={{ type: 'entity', kind: 'similar', entityId: `track:${trackId}` }}
          query={query}
          showLabel
          showStyle={false}
          empty={<Text c="dimmed">{t('similar.none')}</Text>}
        />
      )}
    </Stack>
  );
}
